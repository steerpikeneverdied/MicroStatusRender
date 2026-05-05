from __future__ import annotations

import json
import time
from typing import Any

from .display.sketch_surface import (
    BAR_VALUE_SWAP_MS,
    BAR_VALUE_TRANSITION_MS,
    DEFAULT_BAR_SEGMENTS,
    DEFAULT_OLED_CONTRAST,
    ITEMS_PER_METRIC_PAGE,
    MAX_BAR_SEGMENTS,
    MAX_TITLE_STORAGE_CHARS,
    MAX_UNIT_STORAGE_CHARS,
    MAX_VALUE_STORAGE_CHARS,
    METRIC_FADE_OUT_MS,
    METRIC_MARQUEE_STEP_MS,
    METRIC_PAGE_HOLD_MS,
    METRIC_TITLE_SCROLL_MS,
    METRIC_VALUE_START_X,
    OLED_HEIGHT,
    OLED_WIDTH,
    ease_out_cubic,
    metric_contrast_for_fade_progress,
    metric_page_has_overflow,
    metric_value_progress_for_row,
    metric_value_intro_duration_ms,
    sanitize_display_text,
)


DEFAULT_LAYOUT = {"width": OLED_WIDTH, "height": OLED_HEIGHT, "rows": ITEMS_PER_METRIC_PAGE}
DEFAULT_FALLBACK = {"title": "Status", "value": "Idle"}
MAX_RENDER_ITEMS = 24
SHOW_VALUE_KEYS = {"SHOW_VALUE", "SHOWVALUE", "DISPLAY_VALUE"}
PHASE_TITLE_INTRO = "title_intro"
PHASE_VALUE_INTRO = "value_intro"
PHASE_HOLD = "hold"
PHASE_FADE_OUT = "fade_out"


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def normalize_render_payload(payload: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict) and "items" in payload:
        items = [_normalize_item_dict(item) for item in payload.get("items") or []]
        return {
            "layout": dict(DEFAULT_LAYOUT),
            "items": items or [_fallback_item()],
            "fallback": dict(DEFAULT_FALLBACK),
        }

    normalized = str(payload or "").replace("\r", "")
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if lines and lines[0].upper() == "CLEAR_OLD":
        lines = lines[1:]

    items: list[dict[str, Any]] = []
    index = 0
    while index < len(lines) and len(items) < MAX_RENDER_ITEMS:
        title = sanitize_display_text(lines[index], MAX_TITLE_STORAGE_CHARS)
        index += 1
        if index >= len(lines):
            raise ValueError(f"Missing value line for title '{title}'.")
        item_type, value_payload = parse_value_line(lines[index])
        items.append({"title": title, "value_type": item_type, **value_payload})
        index += 1

    return {
        "layout": dict(DEFAULT_LAYOUT),
        "items": items or [_fallback_item()],
        "fallback": dict(DEFAULT_FALLBACK),
    }


def build_frame(
    payload: str | dict[str, Any],
    page_index: int = 0,
    *,
    phase: str = PHASE_HOLD,
    phase_elapsed_ms: int = 0,
    hold_elapsed_ms: int = 0,
) -> dict[str, Any]:
    normalized = normalize_render_payload(payload)
    page_items = _page_items(normalized["items"], page_index)
    if phase == PHASE_TITLE_INTRO:
        progress = ease_out_cubic(float(phase_elapsed_ms) / float(METRIC_TITLE_SCROLL_MS))
        title_offset_y = int(float(OLED_HEIGHT) * (1.0 - progress) + 0.5)
        return _metric_frame(
            normalized,
            page_items,
            page_index=page_index,
            phase=phase,
            title_offset_y=title_offset_y,
            show_values=False,
            value_elapsed_ms=metric_value_intro_duration_ms(len(page_items)),
            marquee_elapsed_ms=0,
            hold_elapsed_ms=0,
            contrast=DEFAULT_OLED_CONTRAST,
        )
    if phase == PHASE_VALUE_INTRO:
        return _metric_frame(
            normalized,
            page_items,
            page_index=page_index,
            phase=phase,
            title_offset_y=0,
            show_values=True,
            value_elapsed_ms=phase_elapsed_ms,
            marquee_elapsed_ms=0,
            hold_elapsed_ms=0,
            contrast=DEFAULT_OLED_CONTRAST,
        )
    if phase == PHASE_FADE_OUT:
        return _metric_frame(
            normalized,
            page_items,
            page_index=page_index,
            phase=phase,
            title_offset_y=0,
            show_values=True,
            value_elapsed_ms=metric_value_intro_duration_ms(len(page_items)),
            marquee_elapsed_ms=hold_elapsed_ms,
            hold_elapsed_ms=hold_elapsed_ms,
            contrast=metric_contrast_for_fade_progress(float(phase_elapsed_ms) / float(METRIC_FADE_OUT_MS)),
        )
    return _metric_frame(
        normalized,
        page_items,
        page_index=page_index,
        phase=PHASE_HOLD,
        title_offset_y=0,
        show_values=True,
        value_elapsed_ms=metric_value_intro_duration_ms(len(page_items)),
        marquee_elapsed_ms=hold_elapsed_ms,
        hold_elapsed_ms=hold_elapsed_ms,
        contrast=DEFAULT_OLED_CONTRAST,
    )


class MicrostatusRenderer:
    def __init__(self, display, *, monotonic=time.monotonic):
        self.display = display
        self._monotonic = monotonic
        self._payload_signature: str | None = None
        self._payload = normalize_render_payload("")
        self._active_page_items = _page_items(self._payload["items"], 0)
        self._mode = "status"
        self._status_lines = ["MICROSTATUS", "CONNECTING", "WAIT FOR SERVER", ""]
        self._page_index = 0
        self._phase = PHASE_TITLE_INTRO
        self._phase_started_at = self._monotonic()
        self._hold_started_at = 0.0
        self._last_frame: dict[str, Any] | None = None
        self._last_visual_signature: tuple[Any, ...] | None = None
        self._active_page_overflow = metric_page_has_overflow(self._active_page_items)

    def update_payload(self, payload: str | dict[str, Any], *, now: float | None = None) -> None:
        timestamp = self._monotonic() if now is None else now
        normalized = normalize_render_payload(payload)
        signature = json.dumps(normalized, sort_keys=True, default=str)
        if signature == self._payload_signature and self._mode == "metric":
            return
        self._payload_signature = signature
        self._payload = normalized
        if self._mode != "metric" or _page_is_fallback(self._active_page_items):
            self._activate_page(0, now=timestamp)
            self._last_frame = None
            self._last_visual_signature = None
            return

        self._active_page_items = _merge_visible_items(self._active_page_items, self._payload["items"])
        self._active_page_overflow = metric_page_has_overflow(self._active_page_items)
        self._mode = "metric"
        self._last_frame = None
        self._last_visual_signature = None

    def show_connecting(self, *, now: float | None = None) -> None:
        del now
        self._set_status_lines(["MICROSTATUS", "CONNECTING", "WAIT FOR SERVER", ""])

    def show_disconnected(self, detail: str = "", *, now: float | None = None) -> None:
        del now
        detail_line = str(detail or "").replace("\r", " ").replace("\n", " ")
        self._set_status_lines(["MICROSTATUS", "DISCONNECTED", "RETRYING", detail_line])

    def render_payload(self, payload: str | dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
        timestamp = self._monotonic() if now is None else now
        self.update_payload(payload, now=timestamp)
        return self.render_next_frame(now=timestamp)

    def render_disconnected(self, detail: str = "", *, now: float | None = None) -> dict[str, Any]:
        timestamp = self._monotonic() if now is None else now
        self.show_disconnected(detail, now=timestamp)
        return self.render_next_frame(now=timestamp)

    def render_next_frame(self, *, now: float | None = None) -> dict[str, Any]:
        timestamp = self._monotonic() if now is None else now
        if self._mode == "status":
            frame = self._status_frame()
        else:
            frame = self._metric_frame(timestamp)
        visual_signature = _frame_visual_signature(frame)
        if visual_signature != self._last_visual_signature:
            self.display.render_frame(frame)
            self._last_frame = frame
            self._last_visual_signature = visual_signature
        return frame

    def _metric_frame(self, now: float) -> dict[str, Any]:
        page_items = list(self._active_page_items)
        phase_elapsed_ms = _elapsed_ms(self._phase_started_at, now)
        hold_elapsed_ms = _elapsed_ms(self._hold_started_at, now) if self._hold_started_at else 0

        if self._phase == PHASE_TITLE_INTRO and phase_elapsed_ms >= METRIC_TITLE_SCROLL_MS:
            self._phase = PHASE_VALUE_INTRO
            self._phase_started_at = now
            return _metric_frame_dict(
                self._payload,
                page_items,
                page_index=self._page_index,
                phase=PHASE_VALUE_INTRO,
                title_offset_y=0,
                show_values=True,
                value_elapsed_ms=0,
                marquee_elapsed_ms=0,
                hold_elapsed_ms=0,
                contrast=DEFAULT_OLED_CONTRAST,
                overflow=self._active_page_overflow,
            )

        if self._phase == PHASE_VALUE_INTRO:
            intro_duration_ms = metric_value_intro_duration_ms(len(page_items))
            if phase_elapsed_ms >= intro_duration_ms:
                self._phase = PHASE_HOLD
                self._phase_started_at = now
                self._hold_started_at = now
                return _metric_frame_dict(
                    self._payload,
                    page_items,
                    page_index=self._page_index,
                    phase=PHASE_HOLD,
                    title_offset_y=0,
                    show_values=True,
                    value_elapsed_ms=intro_duration_ms,
                    marquee_elapsed_ms=0,
                    hold_elapsed_ms=0,
                    contrast=DEFAULT_OLED_CONTRAST,
                    overflow=self._active_page_overflow,
                )

        if self._phase == PHASE_HOLD:
            frame = _metric_frame_dict(
                self._payload,
                page_items,
                page_index=self._page_index,
                phase=PHASE_HOLD,
                title_offset_y=0,
                show_values=True,
                value_elapsed_ms=metric_value_intro_duration_ms(len(page_items)),
                marquee_elapsed_ms=hold_elapsed_ms,
                hold_elapsed_ms=hold_elapsed_ms,
                contrast=DEFAULT_OLED_CONTRAST,
                overflow=self._active_page_overflow,
            )
            if phase_elapsed_ms >= METRIC_PAGE_HOLD_MS:
                self._phase = PHASE_FADE_OUT
                self._phase_started_at = now
            return frame

        if self._phase == PHASE_FADE_OUT:
            frame = _metric_frame_dict(
                self._payload,
                page_items,
                page_index=self._page_index,
                phase=PHASE_FADE_OUT,
                title_offset_y=0,
                show_values=True,
                value_elapsed_ms=metric_value_intro_duration_ms(len(page_items)),
                marquee_elapsed_ms=hold_elapsed_ms,
                hold_elapsed_ms=hold_elapsed_ms,
                contrast=metric_contrast_for_fade_progress(float(phase_elapsed_ms) / float(METRIC_FADE_OUT_MS)),
                overflow=self._active_page_overflow,
            )
            if phase_elapsed_ms >= METRIC_FADE_OUT_MS:
                self._advance_page(now)
                return {
                    "mode": "blank",
                    "layout": dict(DEFAULT_LAYOUT),
                    "enabled": False,
                    "contrast": DEFAULT_OLED_CONTRAST,
                    "phase": "blank",
                }
            return frame

        return _metric_frame_dict(
            self._payload,
            page_items,
            page_index=self._page_index,
            phase=self._phase,
            title_offset_y=0,
            show_values=self._phase != PHASE_TITLE_INTRO,
            value_elapsed_ms=phase_elapsed_ms if self._phase == PHASE_VALUE_INTRO else metric_value_intro_duration_ms(len(page_items)),
            marquee_elapsed_ms=hold_elapsed_ms,
            hold_elapsed_ms=hold_elapsed_ms,
            contrast=DEFAULT_OLED_CONTRAST,
            overflow=self._active_page_overflow,
        )

    def _advance_page(self, now: float) -> None:
        page_count = max(1, (len(self._payload["items"]) + ITEMS_PER_METRIC_PAGE - 1) // ITEMS_PER_METRIC_PAGE)
        self._activate_page((self._page_index + 1) % page_count, now=now)

    def _activate_page(self, page_index: int, *, now: float) -> None:
        page_count = max(1, (len(self._payload["items"]) + ITEMS_PER_METRIC_PAGE - 1) // ITEMS_PER_METRIC_PAGE)
        self._page_index = page_index % page_count
        self._active_page_items = _page_items(self._payload["items"], self._page_index)
        self._active_page_overflow = metric_page_has_overflow(self._active_page_items)
        self._mode = "metric"
        self._phase = PHASE_TITLE_INTRO
        self._phase_started_at = now
        self._hold_started_at = 0.0

    def _set_status_lines(self, lines: list[str]) -> None:
        normalized_lines = [str(line or "").replace("\r", " ").replace("\n", " ")[:21] for line in lines[:4]]
        while len(normalized_lines) < 4:
            normalized_lines.append("")
        if self._mode == "status" and self._status_lines == normalized_lines:
            return
        self._mode = "status"
        self._status_lines = normalized_lines
        self._last_frame = None
        self._last_visual_signature = None

    def _status_frame(self) -> dict[str, Any]:
        return {
            "mode": "status",
            "layout": dict(DEFAULT_LAYOUT),
            "enabled": True,
            "contrast": DEFAULT_OLED_CONTRAST,
            "lines": list(self._status_lines),
        }


def parse_value_line(line: str) -> tuple[str, dict[str, Any]]:
    trimmed = line.replace("\r", " ").replace("\n", " ").strip()
    if not trimmed:
        raise ValueError("Value line is empty.")
    upper = trimmed.upper()
    if upper.startswith("BAR") or upper.startswith("SEGMENTS"):
        return "bar", _parse_bar_value_line(trimmed)
    return "text", _parse_text_value_line(trimmed)


def _parse_text_value_line(line: str) -> dict[str, Any]:
    tokens = [token for token in line.split(" ") if token]
    value_tokens: list[str] = []
    unit = ""
    for token in tokens:
        key, value = _split_argument_token(token)
        if key in {"UNIT", "U"}:
            unit = value
        else:
            value_tokens.append(token)
    value_text = sanitize_display_text(" ".join(value_tokens).strip() or line, MAX_VALUE_STORAGE_CHARS)
    if not value_text:
        raise ValueError("Text value line must include a value.")
    return {
        "value": value_text,
        "unit": sanitize_display_text(unit, MAX_UNIT_STORAGE_CHARS),
    }


def _parse_bar_value_line(line: str) -> dict[str, Any]:
    first_space = line.find(" ")
    spec = line[first_space + 1 :] if first_space >= 0 else ""
    spec = spec.replace(",", " ").replace(";", " ").strip()
    tokens = [token for token in spec.split(" ") if token]

    minimum = 0.0
    maximum = 100.0
    current = 0.0
    segment_count = DEFAULT_BAR_SEGMENTS
    unit = ""
    show_current_value = False
    has_current = False
    bare_value_index = 0

    for token in tokens:
        key, value = _split_argument_token(token)
        if key == "MIN":
            minimum = _parse_float(value, "MIN")
            continue
        if key == "MAX":
            maximum = _parse_float(value, "MAX")
            continue
        if key in {"CURRENT", "VALUE"}:
            current = _parse_float(value, key)
            has_current = True
            continue
        if key in {"SEGMENTS", "SEGS"}:
            segment_count = _parse_int(value, key)
            continue
        if key in {"UNIT", "U"}:
            unit = value
            continue
        if key in SHOW_VALUE_KEYS:
            show_current_value = parse_bool(value, False)
            continue
        if key is not None:
            raise ValueError(f"Unexpected BAR argument '{key}'.")

        numeric_value = _parse_float(value, value)
        if bare_value_index == 0:
            minimum = numeric_value
        elif bare_value_index == 1:
            maximum = numeric_value
        elif bare_value_index == 2:
            current = numeric_value
            has_current = True
        elif bare_value_index == 3:
            segment_count = int(numeric_value)
        else:
            raise ValueError(f"Unexpected BAR token '{value}'.")
        bare_value_index += 1

    if not has_current:
        raise ValueError("BAR lines require CURRENT.")
    if maximum <= minimum:
        raise ValueError("BAR MAX must be greater than MIN.")
    if segment_count < 1:
        raise ValueError("BAR SEGMENTS must be at least one.")
    return {
        "min_value": minimum,
        "max_value": maximum,
        "current_value": current,
        "segment_count": min(MAX_BAR_SEGMENTS, segment_count),
        "unit": sanitize_display_text(unit, MAX_UNIT_STORAGE_CHARS),
        "show_current_value": show_current_value,
    }


def _metric_frame(
    normalized: dict[str, Any],
    page_items: list[dict[str, Any]],
    *,
    page_index: int,
    phase: str,
    title_offset_y: int,
    show_values: bool,
    value_elapsed_ms: int,
    marquee_elapsed_ms: int,
    hold_elapsed_ms: int,
    contrast: int,
) -> dict[str, Any]:
    return {
        "mode": "metric",
        "layout": dict(normalized["layout"]),
        "enabled": True,
        "contrast": contrast,
        "phase": phase,
        "page_index": page_index,
        "page_count": max(1, (len(normalized["items"]) + ITEMS_PER_METRIC_PAGE - 1) // ITEMS_PER_METRIC_PAGE),
        "items": page_items,
        "title_offset_y": title_offset_y,
        "show_values": show_values,
        "value_elapsed_ms": max(0, value_elapsed_ms),
        "marquee_elapsed_ms": max(0, marquee_elapsed_ms),
        "hold_elapsed_ms": max(0, hold_elapsed_ms),
        "overflow": metric_page_has_overflow(page_items),
    }


def _metric_frame_dict(
    normalized: dict[str, Any],
    page_items: list[dict[str, Any]],
    *,
    page_index: int,
    phase: str,
    title_offset_y: int,
    show_values: bool,
    value_elapsed_ms: int,
    marquee_elapsed_ms: int,
    hold_elapsed_ms: int,
    contrast: int,
    overflow: bool,
) -> dict[str, Any]:
    return {
        "mode": "metric",
        "layout": dict(normalized["layout"]),
        "enabled": True,
        "contrast": contrast,
        "phase": phase,
        "page_index": page_index,
        "page_count": max(1, (len(normalized["items"]) + ITEMS_PER_METRIC_PAGE - 1) // ITEMS_PER_METRIC_PAGE),
        "items": list(page_items),
        "title_offset_y": title_offset_y,
        "show_values": show_values,
        "value_elapsed_ms": max(0, value_elapsed_ms),
        "marquee_elapsed_ms": max(0, marquee_elapsed_ms),
        "hold_elapsed_ms": max(0, hold_elapsed_ms),
        "overflow": overflow,
    }


def _frame_visual_signature(frame: dict[str, Any]) -> tuple[Any, ...]:
    mode = str(frame.get("mode") or "")
    enabled = bool(frame.get("enabled", True))
    contrast = int(frame.get("contrast", DEFAULT_OLED_CONTRAST))
    if mode == "status":
        return (mode, enabled, contrast, tuple(frame.get("lines") or []))
    if mode == "blank":
        return (mode, enabled, contrast)

    items = list(frame.get("items") or [])
    item_signatures = tuple(_item_visual_signature(item) for item in items)
    page_index = int(frame.get("page_index") or 0)
    phase = str(frame.get("phase") or "")

    if phase == PHASE_TITLE_INTRO:
        return (
            mode,
            enabled,
            contrast,
            page_index,
            phase,
            int(frame.get("title_offset_y") or 0),
            item_signatures,
        )

    if phase == PHASE_VALUE_INTRO:
        item_count = min(len(items), ITEMS_PER_METRIC_PAGE)
        value_elapsed_ms = int(frame.get("value_elapsed_ms") or 0)
        return (
            mode,
            enabled,
            contrast,
            page_index,
            phase,
            item_signatures,
            tuple(
                _value_intro_row_signature(item, row, item_count, value_elapsed_ms)
                for row, item in enumerate(items[:ITEMS_PER_METRIC_PAGE])
            ),
        )

    hold_elapsed_ms = int(frame.get("hold_elapsed_ms") or 0)
    marquee_step = hold_elapsed_ms // METRIC_MARQUEE_STEP_MS if bool(frame.get("overflow")) else -1
    return (
        mode,
        enabled,
        contrast,
        page_index,
        phase,
        item_signatures,
        marquee_step,
        tuple(_bar_hold_signature(item, hold_elapsed_ms) for item in items if item.get("value_type") == "bar"),
    )


def _item_visual_signature(item: dict[str, Any]) -> tuple[Any, ...]:
    value_type = str(item.get("value_type") or "text")
    if value_type == "bar":
        return (
            value_type,
            str(item.get("title") or ""),
            float(item.get("min_value", 0.0)),
            float(item.get("max_value", 100.0)),
            float(item.get("current_value", 0.0)),
            int(item.get("segment_count", DEFAULT_BAR_SEGMENTS)),
            str(item.get("unit") or ""),
            bool(item.get("show_current_value")),
        )
    return (
        value_type,
        str(item.get("title") or ""),
        str(item.get("value") or ""),
        str(item.get("unit") or ""),
    )


def _value_intro_row_signature(
    item: dict[str, Any],
    row: int,
    item_count: int,
    value_elapsed_ms: int,
) -> tuple[Any, ...] | None:
    if item.get("value_type") == "text" and not str(item.get("value") or ""):
        return None
    value_progress = metric_value_progress_for_row(item_count, row, value_elapsed_ms)
    if value_progress <= 0.0:
        return None
    value_travel = float(OLED_WIDTH - METRIC_VALUE_START_X) * (1.0 - value_progress)
    return (row, int(value_travel + 0.5))


def _bar_hold_signature(item: dict[str, Any], hold_elapsed_ms: int) -> tuple[Any, ...]:
    if not item.get("show_current_value") or hold_elapsed_ms < BAR_VALUE_SWAP_MS:
        return ("bar",)

    mode_index = hold_elapsed_ms // BAR_VALUE_SWAP_MS
    mode_elapsed_ms = hold_elapsed_ms % BAR_VALUE_SWAP_MS
    show_bar = (mode_index % 2) == 0
    if mode_elapsed_ms >= BAR_VALUE_TRANSITION_MS:
        return ("steady", show_bar)

    progress = ease_out_cubic(float(mode_elapsed_ms) / float(BAR_VALUE_TRANSITION_MS))
    value_row_height_px = 8
    incoming_offset_y = int(float(value_row_height_px) * (1.0 - progress) + 0.5)
    outgoing_offset_y = int(float(value_row_height_px) * progress + 0.5)
    return ("transition", show_bar, incoming_offset_y, outgoing_offset_y)


def _page_items(items: list[dict[str, Any]], page_index: int) -> list[dict[str, Any]]:
    if not items:
        return [_fallback_item()]
    start = (page_index % max(1, (len(items) + ITEMS_PER_METRIC_PAGE - 1) // ITEMS_PER_METRIC_PAGE)) * ITEMS_PER_METRIC_PAGE
    return items[start : start + ITEMS_PER_METRIC_PAGE]


def _merge_visible_items(active_items: list[dict[str, Any]], latest_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_title = {
        str(item.get("title") or "").casefold(): item
        for item in latest_items
        if str(item.get("title") or "").strip()
    }
    merged: list[dict[str, Any]] = []
    for item in active_items:
        title_key = str(item.get("title") or "").casefold()
        merged.append(latest_by_title.get(title_key, item))
    return merged or [_fallback_item()]


def _page_is_fallback(items: list[dict[str, Any]]) -> bool:
    if len(items) != 1:
        return False
    item = items[0]
    return (
        item.get("value_type") == "text"
        and item.get("title") == DEFAULT_FALLBACK["title"]
        and item.get("value") == DEFAULT_FALLBACK["value"]
    )


def _normalize_item_dict(item: dict[str, Any]) -> dict[str, Any]:
    item_type = str(item.get("value_type") or item.get("type") or "text").lower()
    title = sanitize_display_text(str(item.get("title") or ""), MAX_TITLE_STORAGE_CHARS)
    if item_type == "bar":
        return {
            "title": title,
            "value_type": "bar",
            "min_value": float(item.get("min_value", item.get("min", 0.0))),
            "max_value": float(item.get("max_value", item.get("max", 100.0))),
            "current_value": float(item.get("current_value", item.get("current", 0.0))),
            "segment_count": min(MAX_BAR_SEGMENTS, int(item.get("segment_count", item.get("segments", DEFAULT_BAR_SEGMENTS)))),
            "unit": sanitize_display_text(str(item.get("unit") or ""), MAX_UNIT_STORAGE_CHARS),
            "show_current_value": parse_bool(item.get("show_current_value", item.get("show_value")), False),
        }
    return {
        "title": title,
        "value_type": "text",
        "value": sanitize_display_text(str(item.get("value") or ""), MAX_VALUE_STORAGE_CHARS),
        "unit": sanitize_display_text(str(item.get("unit") or ""), MAX_UNIT_STORAGE_CHARS),
    }


def _fallback_item() -> dict[str, Any]:
    return {
        "title": sanitize_display_text(DEFAULT_FALLBACK["title"], MAX_TITLE_STORAGE_CHARS),
        "value_type": "text",
        "value": sanitize_display_text(DEFAULT_FALLBACK["value"], MAX_VALUE_STORAGE_CHARS),
        "unit": "",
    }


def _split_argument_token(token: str) -> tuple[str | None, str]:
    if "=" not in token:
        return None, token
    key, value = token.split("=", 1)
    normalized_key = key.strip().upper()
    return normalized_key or None, value.strip()


def _parse_float(value: str, label: str) -> float:
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"{label} must be numeric.") from error


def _parse_int(value: str, label: str) -> int:
    try:
        return int(float(value))
    except ValueError as error:
        raise ValueError(f"{label} must be numeric.") from error


def _elapsed_ms(started_at: float, now: float) -> int:
    return int(max(0.0, now - started_at) * 1000)
