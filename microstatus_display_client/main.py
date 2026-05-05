from __future__ import annotations

import gc
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass

from .client import MicrostatusApiClient, MicrostatusApiError, MicrostatusClientConfig
from .display.console import ConsoleDisplay
from .display.null import NullDisplay
from .display.sketch_surface import DISPLAY_FRAME_INTERVAL_MS, ITEMS_PER_METRIC_PAGE
from .display.ssd1306 import DisplayInitError, SSD1306Display
from .renderer import MicrostatusRenderer


LOGGER = logging.getLogger("microstatus-display-client")


@dataclass(frozen=True)
class DisplayRuntimeConfig:
    api_base: str
    display_id: str
    display_name: str
    location: str | None
    poll_interval: float
    mode: str
    auth_token: str | None
    i2c_bus: int
    oled_address: int
    oled_width: int
    oled_height: int
    rows: int


def load_config() -> DisplayRuntimeConfig:
    api_base = _require_env("MICROSTATUS_API_BASE")
    display_id = _require_env("MICROSTATUS_DISPLAY_ID")
    display_name = _require_env("MICROSTATUS_DISPLAY_NAME")
    return DisplayRuntimeConfig(
        api_base=api_base,
        display_id=display_id,
        display_name=display_name,
        location=os.getenv("MICROSTATUS_DISPLAY_LOCATION"),
        poll_interval=max(0.2, _read_float(os.getenv("MICROSTATUS_POLL_INTERVAL"), 1.0)),
        mode=(os.getenv("MICROSTATUS_DISPLAY_MODE") or "auto").strip().lower(),
        auth_token=os.getenv("MICROSTATUS_API_TOKEN"),
        i2c_bus=_read_int(os.getenv("MICROSTATUS_I2C_BUS"), 1),
        oled_address=_read_int(os.getenv("MICROSTATUS_OLED_ADDRESS"), 0x3C, base=0),
        oled_width=_read_int(os.getenv("MICROSTATUS_OLED_WIDTH"), 128),
        oled_height=_read_int(os.getenv("MICROSTATUS_OLED_HEIGHT"), 32),
        rows=max(1, _read_int(os.getenv("MICROSTATUS_ROWS"), ITEMS_PER_METRIC_PAGE)),
    )


def create_display_backend(config: DisplayRuntimeConfig):
    if config.mode == "null":
        return NullDisplay()
    if config.mode == "console":
        return ConsoleDisplay()

    try:
        return SSD1306Display(
            i2c_bus=config.i2c_bus,
            address=config.oled_address,
            width=config.oled_width,
            height=config.oled_height,
        )
    except DisplayInitError as error:
        LOGGER.warning("Falling back to console display: %s", error)
        return ConsoleDisplay()


def build_capabilities(config: DisplayRuntimeConfig) -> dict[str, object]:
    return {
        "width": config.oled_width,
        "height": config.oled_height,
        "rows": ITEMS_PER_METRIC_PAGE,
        "supported_types": ["text", "bar"],
        "supports_bar": True,
        "max_items": 24,
        "render_protocol": "sketch-plain-v1",
    }


def build_metadata(display_backend) -> dict[str, object]:
    return {
        "backend": display_backend.__class__.__name__,
        "hostname": socket.gethostname(),
    }


def run_forever() -> None:
    config = load_config()
    display_backend = create_display_backend(config)
    renderer = MicrostatusRenderer(display_backend, monotonic=time.perf_counter)
    client = MicrostatusApiClient(
        MicrostatusClientConfig(
            api_base=config.api_base,
            display_id=config.display_id,
            display_name=config.display_name,
            location=config.location,
            auth_token=config.auth_token,
        )
    )
    capabilities = build_capabilities(config)
    renderer.show_connecting()
    gc.disable()

    frame_interval_seconds = DISPLAY_FRAME_INTERVAL_MS / 1000.0
    next_frame_at = time.perf_counter()
    state_lock = threading.Lock()
    stop_event = threading.Event()
    state = {"version": 0, "body": None, "error": None}

    def publish(*, body: str | None = None, error: str | None = None) -> None:
        with state_lock:
            state["version"] += 1
            state["body"] = body
            state["error"] = error

    def poll_loop() -> None:
        registered = False
        while not stop_event.is_set():
            metadata = build_metadata(display_backend)
            try:
                if not registered:
                    client.register_display(capabilities=capabilities, metadata=metadata)
                    registered = True
                client.heartbeat(capabilities=capabilities, metadata=metadata, status="online")
                publish(body=client.fetch_render_body(), error=None)
            except MicrostatusApiError as error:
                registered = False
                publish(body=None, error=str(error))
            except Exception as error:  # pragma: no cover - defensive runtime fallback
                registered = False
                publish(body=None, error=str(error))
            stop_event.wait(config.poll_interval)

    threading.Thread(target=poll_loop, name="microstatus-poll", daemon=True).start()
    last_seen_version = -1

    try:
        while True:
            now = time.perf_counter()
            with state_lock:
                version = int(state["version"])
                body = state["body"]
                error = state["error"]
            if version != last_seen_version:
                last_seen_version = version
                if error:
                    renderer.show_disconnected(str(error), now=now)
                elif body is not None:
                    renderer.update_payload(str(body), now=now)

            if now >= next_frame_at:
                renderer.render_next_frame(now=now)
                next_frame_at += frame_interval_seconds
                if now - next_frame_at > frame_interval_seconds:
                    next_frame_at = now + frame_interval_seconds

            _wait_until(next_frame_at)
    finally:
        stop_event.set()
        gc.enable()


def _wait_until(deadline: float, *, spin_window_seconds: float = 0.0015) -> None:
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return
        if remaining > spin_window_seconds:
            time.sleep(remaining - spin_window_seconds)
            continue


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_forever()


def _require_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} is required.")
    return value


def _read_int(raw_value: str | None, default: int, *, base: int = 10) -> int:
    if raw_value in (None, ""):
        return default
    try:
        return int(str(raw_value), base=base)
    except ValueError:
        return default


def _read_float(raw_value: str | None, default: float) -> float:
    if raw_value in (None, ""):
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


if __name__ == "__main__":
    main()
