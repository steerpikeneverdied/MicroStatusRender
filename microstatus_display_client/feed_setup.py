from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib import parse

from .client import MicrostatusApiClient, MicrostatusApiError, MicrostatusClientConfig


SERVICE_NAME = "microstatus-display-client"
DEFAULT_ENV_FILE = f"/etc/default/{SERVICE_NAME}"
DEFAULT_PAGE_DURATION_MS = 8000


class FeedSetupError(Exception):
    pass


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def merged_env_body(existing_body: str, updates: dict[str, str]) -> str:
    lines = existing_body.splitlines()
    seen: set[str] = set()
    output: list[str] = []

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            output.append(raw_line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(raw_line)

    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")

    return "\n".join(output).strip() + "\n"


def write_env_file(path: Path, updates: dict[str, str]) -> None:
    existing_body = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(merged_env_body(existing_body, updates), encoding="utf-8")


def normalize_api_base(value: str) -> str:
    cleaned = value.strip().rstrip("/")
    parsed = parse.urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise FeedSetupError("MICROSTATUS_API_BASE must look like http://host:18100.")
    return cleaned


def default_display_id() -> str:
    host = socket.gethostname().split(".", 1)[0].strip().lower()
    cleaned = re.sub(r"[^a-z0-9_.-]+", "-", host).strip("-")
    return cleaned or "microstatus-oled"


def prompt_value(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or (default or "")


def parse_section_selection(raw_value: str, section_count: int) -> list[int]:
    normalized = raw_value.strip().lower()
    if normalized in {"all", "*"}:
        return list(range(section_count))

    tokens = [token for token in re.split(r"[\s,]+", normalized) if token]
    if not tokens:
        raise ValueError("Enter at least one number.")

    selected: list[int] = []
    seen: set[int] = set()
    for token in tokens:
        if not token.isdigit():
            raise ValueError(f"'{token}' is not a number.")
        number = int(token)
        if number < 1 or number > section_count:
            raise ValueError(f"{number} is outside the list.")
        index = number - 1
        if index in seen:
            continue
        seen.add(index)
        selected.append(index)
    return selected


def choose_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not sections:
        raise FeedSetupError("Agent Platform returned no Microstatus data sections.")

    print("\nAvailable Microstatus data sections:")
    for index, section in enumerate(sections, start=1):
        key = str(section.get("key") or "")
        name = str(section.get("name") or key)
        description = str(section.get("description") or "")
        print(f"  {index}. {name} ({key})")
        if description:
            print(f"     {description}")

    while True:
        raw_selection = input("\nEnter section numbers, separated by spaces or commas: ").strip()
        try:
            return [sections[index] for index in parse_section_selection(raw_selection, len(sections))]
        except ValueError as error:
            print(f"Invalid selection: {error}")


def positive_int(raw_value: str, label: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{label} must be a number.") from error
    if value <= 0:
        raise argparse.ArgumentTypeError(f"{label} must be greater than zero.")
    return value


def int_env(values: dict[str, str], key: str, default: int) -> int:
    raw_value = values.get(key)
    if not raw_value:
        return default
    try:
        return int(raw_value, 0)
    except ValueError:
        return default


def restart_service(service_name: str) -> None:
    if not shutil.which("systemctl"):
        print("systemctl not found; skipping service restart.")
        return
    subprocess.run(["systemctl", "restart", service_name], check=True)
    print(f"Restarted {service_name}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Choose which Agent Platform Microstatus data sections this OLED display subscribes to.",
    )
    parser.add_argument("--env-file", default=os.getenv("MICROSTATUS_ENV_FILE") or DEFAULT_ENV_FILE)
    parser.add_argument("--api-base", default=os.getenv("MICROSTATUS_API_BASE"))
    parser.add_argument("--display-id", default=os.getenv("MICROSTATUS_DISPLAY_ID"))
    parser.add_argument("--display-name", default=os.getenv("MICROSTATUS_DISPLAY_NAME"))
    parser.add_argument("--location", default=os.getenv("MICROSTATUS_DISPLAY_LOCATION"))
    parser.add_argument("--no-write-env", action="store_true")
    parser.add_argument("--no-restart", action="store_true")
    parser.add_argument(
        "--page-duration-ms",
        type=lambda value: positive_int(value, "page duration"),
        default=DEFAULT_PAGE_DURATION_MS,
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_path = Path(args.env_file)
    env_values = load_env_file(env_path)

    try:
        api_base = normalize_api_base(
            args.api_base
            or env_values.get("MICROSTATUS_API_BASE", "")
            or prompt_value("Agent Platform API URL", "http://127.0.0.1:18100")
        )
        display_id = prompt_value("Display ID", args.display_id or env_values.get("MICROSTATUS_DISPLAY_ID") or default_display_id())
        display_name = prompt_value(
            "Display name",
            args.display_name or env_values.get("MICROSTATUS_DISPLAY_NAME") or display_id,
        )
        location = prompt_value(
            "Display location",
            args.location or env_values.get("MICROSTATUS_DISPLAY_LOCATION") or platform.node() or "microscreen",
        )

        client = MicrostatusApiClient(
            MicrostatusClientConfig(
                api_base=api_base,
                display_id=display_id,
                display_name=display_name,
                location=location,
                auth_token=env_values.get("MICROSTATUS_API_TOKEN") or os.getenv("MICROSTATUS_API_TOKEN"),
                timeout_seconds=10.0,
            )
        )
        sections = client.list_sections()
        selected_sections = choose_sections(sections)
        section_keys = [str(section["key"]) for section in selected_sections]

        width = int_env(env_values, "MICROSTATUS_OLED_WIDTH", 128)
        height = int_env(env_values, "MICROSTATUS_OLED_HEIGHT", 32)
        rows = int_env(env_values, "MICROSTATUS_ROWS", 3)
        capabilities = {
            "width": width,
            "height": height,
            "rows": rows,
            "supported_types": ["text", "bar"],
            "supports_bar": True,
            "bar_supported": True,
            "max_items": 24,
            "render_protocol": "sketch-plain-v1",
        }
        metadata = {
            "hostname": socket.gethostname(),
            "setup_source": "microserverfeed",
            "selected_sections": section_keys,
        }

        client.register_display(capabilities=capabilities, metadata=metadata)
        client.subscribe_display_to_sections(
            section_keys=section_keys,
            layout={"rows": rows, "page_duration_ms": args.page_duration_ms},
        )

        render_url = f"{api_base}/microstatus/displays/{parse.quote(display_id, safe='')}/render/plain"
        updates = {
            "MICROSTATUS_API_BASE": api_base,
            "MICROSTATUS_DISPLAY_ID": display_id,
            "MICROSTATUS_DISPLAY_NAME": display_name,
            "MICROSTATUS_DISPLAY_LOCATION": location,
            "MICROSTATUS_SELECTED_SECTIONS": ",".join(section_keys),
            "MICROSTATUS_RENDER_URL": render_url,
        }
        if not args.no_write_env:
            write_env_file(env_path, updates)
            print(f"Updated {env_path}.")

        print("\nMicrostatus feed setup complete.")
        print(f"Display: {display_id}")
        print(f"Sections: {', '.join(section_keys)}")
        print(f"Render URL: {render_url}")

        if not args.no_restart:
            restart_service(SERVICE_NAME)
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\nSetup canceled.", file=sys.stderr)
        return 130
    except (FeedSetupError, MicrostatusApiError, OSError, subprocess.CalledProcessError) as error:
        print(f"microserverfeed failed: {error}", file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
