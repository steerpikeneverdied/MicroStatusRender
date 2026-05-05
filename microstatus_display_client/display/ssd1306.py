from __future__ import annotations

import logging
import time

from .sketch_surface import DEFAULT_OLED_CONTRAST, SketchCanvas


LOGGER = logging.getLogger("microstatus-display-client.oled")


class DisplayInitError(Exception):
    pass


class SSD1306Display:
    _INIT_COMMANDS = bytes(
        [
            0xAE,
            0xD5,
            0x80,
            0xA8,
            0x1F,
            0xD3,
            0x00,
            0x40,
            0x8D,
            0x14,
            0x20,
            0x00,
            0xA1,
            0xC8,
            0xDA,
            0x02,
            0x81,
            DEFAULT_OLED_CONTRAST,
            0xD9,
            0xF1,
            0xDB,
            0x40,
            0xA4,
            0xA6,
            0x2E,
            0xAF,
        ]
    )

    def __init__(
        self,
        *,
        i2c_bus: int = 1,
        address: int = 0x3C,
        width: int = 128,
        height: int = 32,
    ):
        try:
            from smbus2 import SMBus, i2c_msg
        except Exception as exc:  # pragma: no cover - exercised by fallback tests
            raise DisplayInitError(str(exc) or "SSD1306 dependencies are unavailable.") from exc

        self._smbus_cls = SMBus
        self._i2c_msg = i2c_msg
        self._i2c_bus_num = i2c_bus
        self.address = address
        self.width = width
        self.height = height
        self._page_count = self.height // 8
        self._canvas = SketchCanvas(width, height)
        self._contrast = DEFAULT_OLED_CONTRAST
        self._display_enabled = True
        self._last_recover_attempt_at = 0.0
        self._page_setup_packets = tuple(
            bytes([0x00, 0xB0 | page, 0x00, 0x10]) for page in range(self._page_count)
        )
        self._page_data_buffers = [bytearray(1 + self.width) for _ in range(self._page_count)]
        for buffer in self._page_data_buffers:
            buffer[0] = 0x40
        self._last_sent_pages: list[bytes | None] = [None] * self._page_count
        self._bus = None

        try:
            self._open_bus()
            self._initialize_panel()
        except Exception as exc:  # pragma: no cover - exercised by fallback tests
            self._close_bus()
            raise DisplayInitError(str(exc) or "SSD1306 device initialization failed.") from exc

    def render_frame(self, frame: dict) -> None:
        try:
            self._render_frame_impl(frame)
        except (OSError, TimeoutError) as exc:
            if self._recover_from_io_error(exc):
                try:
                    self._render_frame_impl(frame)
                except (OSError, TimeoutError) as retry_exc:
                    LOGGER.warning("OLED redraw failed after recovery attempt: %s", retry_exc)

    def _render_frame_impl(self, frame: dict) -> None:
        if frame.get("mode") == "blank":
            self._canvas.clear()
        elif frame.get("mode") == "status":
            self._canvas.render_status(list(frame.get("lines") or []))
        else:
            self._canvas.render_metric(frame)

        enabled = bool(frame.get("enabled", True))
        self._set_contrast(int(frame.get("contrast", DEFAULT_OLED_CONTRAST)))
        self._set_display_enabled(enabled)
        if enabled:
            self._display_canvas()
        else:
            self._last_sent_pages = [None] * self._page_count

    def _open_bus(self) -> None:
        self._close_bus()
        self._bus = self._smbus_cls(self._i2c_bus_num)

    def _close_bus(self) -> None:
        bus = getattr(self, "_bus", None)
        if bus is None:
            return
        try:
            bus.close()
        except Exception:
            pass
        self._bus = None

    def _initialize_panel(self) -> None:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                self._write_command_list(self._INIT_COMMANDS)
                self._canvas.clear()
                self._last_sent_pages = [None] * self._page_count
                self._display_canvas(force=True)
                return
            except (OSError, TimeoutError) as exc:
                last_error = exc
                if attempt >= 2:
                    break
                time.sleep(0.05)
                self._open_bus()
        if last_error is not None:
            raise last_error

    def _recover_from_io_error(self, error: Exception) -> bool:
        now = time.monotonic()
        if now - self._last_recover_attempt_at < 1.0:
            LOGGER.warning("OLED I2C write failed: %s", error)
            return False

        self._last_recover_attempt_at = now
        LOGGER.warning("OLED I2C write failed, attempting recovery: %s", error)
        try:
            self._open_bus()
            self._initialize_panel()
        except Exception as exc:
            LOGGER.warning("OLED recovery failed: %s", exc)
            return False
        LOGGER.info("OLED recovery succeeded")
        return True

    def _display_canvas(self, *, force: bool = False) -> None:
        page_bytes = memoryview(self._canvas.buffer)
        for page in range(self._page_count):
            start = page * self.width
            end = start + self.width
            current_page = page_bytes[start:end]
            if not force and self._last_sent_pages[page] == current_page:
                continue
            data_buffer = self._page_data_buffers[page]
            data_buffer[1:] = current_page
            self._bus.i2c_rdwr(
                self._i2c_msg.write(self.address, self._page_setup_packets[page]),
                self._i2c_msg.write(self.address, data_buffer),
            )
            self._last_sent_pages[page] = bytes(current_page)

    def _set_contrast(self, contrast: int) -> None:
        contrast = max(0, min(255, int(contrast)))
        if self._contrast == contrast:
            return
        self._write_command_list(bytes([0x81, contrast]))
        self._contrast = contrast

    def _set_display_enabled(self, enabled: bool) -> None:
        if self._display_enabled == enabled:
            return
        self._write_command_list(bytes([0xAF if enabled else 0xAE]))
        self._display_enabled = enabled

    def _write_command_list(self, commands: bytes) -> None:
        self._bus.i2c_rdwr(self._i2c_msg.write(self.address, bytes([0x00]) + commands))

    def _write_data(self, data: bytes) -> None:
        self._bus.i2c_rdwr(self._i2c_msg.write(self.address, bytes([0x40]) + data))

    @property
    def address(self) -> int:
        return getattr(self, "_address", 0x3C)

    @address.setter
    def address(self, value: int) -> None:
        self._address = value
