from __future__ import annotations

from dataclasses import dataclass

from .sketch_fonts import DOGICA_GLYPHS, STATUS_GLYPHS


OLED_WIDTH = 128
OLED_HEIGHT = 32
DEFAULT_OLED_CONTRAST = 0xFF
DISPLAY_FRAME_INTERVAL_MS = 33
METRIC_PAGE_HOLD_MS = 10000
METRIC_TITLE_SCROLL_MS = 400
METRIC_VALUE_REVEAL_MS = 400
METRIC_VALUE_STAGGER_MS = 100
METRIC_FADE_OUT_MS = 2000
BAR_VALUE_SWAP_MS = 2000
BAR_VALUE_TRANSITION_MS = 300
METRIC_MARQUEE_STEP_MS = DISPLAY_FRAME_INTERVAL_MS
METRIC_MARQUEE_GAP_CHARS = 3
ITEMS_PER_METRIC_PAGE = 3
DEFAULT_BAR_SEGMENTS = 10
MAX_BAR_SEGMENTS = 20
BAR_SEGMENT_GAP_PX = 1
BAR_HEIGHT_PX = 6
MAX_UNIT_STORAGE_CHARS = 8
METRIC_GLYPH_WIDTH_PX = 8
METRIC_GLYPH_HEIGHT_PX = 8
METRIC_LETTER_GAP_PX = 1
METRIC_SPACE_ADVANCE_PX = 4
METRIC_TITLE_WIDTH_PX = 50
METRIC_DIVIDER_X = 53
METRIC_VALUE_START_X = 58
METRIC_VALUE_WIDTH_PX = OLED_WIDTH - METRIC_VALUE_START_X
MAX_TITLE_STORAGE_CHARS = 24
MAX_VALUE_STORAGE_CHARS = 32
DISPLAY_DEGREE_PLACEHOLDER = "^"
DISPLAY_OMEGA_PLACEHOLDER = "~"
DISPLAY_UNIT_GAP_PLACEHOLDER = "`"
_STATUS_UNKNOWN_GLYPH = (0x02, 0x01, 0x59, 0x09, 0x06)
_STATUS_LINE_WIDTH = OLED_WIDTH // 6
_LINE_Y = (2, 12, 22)
_DEGREE_CHARS = {"°", "º"}
_OMEGA_CHARS = {"Ω", "Ω"}
_SUPPORTED_DISPLAY_CHARS = {
    " ",
    ".",
    ":",
    "-",
    "/",
    "%",
    "+",
    "_",
    DISPLAY_DEGREE_PLACEHOLDER,
    DISPLAY_OMEGA_PLACEHOLDER,
    DISPLAY_UNIT_GAP_PLACEHOLDER,
}


def clamp_unit_float(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def ease_out_cubic(value: float) -> float:
    value = clamp_unit_float(value)
    inverse = 1.0 - value
    return 1.0 - inverse * inverse * inverse


def is_supported_display_char(char: str) -> bool:
    if len(char) != 1:
        return False
    return char.isalpha() or char.isdigit() or char in _SUPPORTED_DISPLAY_CHARS


def sanitize_display_text(text: str, max_chars: int) -> str:
    return _normalize_display_text(text, max_chars=max_chars, placeholder_mode=False)


def normalize_metric_display_text(text: str) -> str:
    return _normalize_display_text(text, max_chars=None, placeholder_mode=True)


def format_value_with_unit(value: str, unit: str | None) -> str:
    if not unit:
        return str(value)
    return f"{value}{DISPLAY_UNIT_GAP_PLACEHOLDER}{unit}"


def metric_advance(char: str) -> int:
    if char == DISPLAY_UNIT_GAP_PLACEHOLDER:
        return 1
    glyph = metric_glyph_for(char)
    first_col = METRIC_GLYPH_WIDTH_PX
    last_col = -1
    for col, column_bits in enumerate(glyph):
        if column_bits:
            if first_col == METRIC_GLYPH_WIDTH_PX:
                first_col = col
            last_col = col
    if last_col < first_col:
        return METRIC_SPACE_ADVANCE_PX
    return (last_col - first_col + 1) + METRIC_LETTER_GAP_PX


def measure_metric_text(text: str) -> int:
    normalized = normalize_metric_display_text(text)
    width = sum(metric_advance(char) for char in normalized)
    if normalized and width > 0:
        width -= METRIC_LETTER_GAP_PX
    return width


def metric_value_intro_duration_ms(item_count: int) -> int:
    if item_count <= 0:
        return 0
    return METRIC_VALUE_REVEAL_MS + METRIC_VALUE_STAGGER_MS * (item_count - 1)


def metric_value_progress_for_row(item_count: int, row: int, value_elapsed_ms: int) -> float:
    intro_duration_ms = metric_value_intro_duration_ms(item_count)
    if intro_duration_ms == 0 or value_elapsed_ms >= intro_duration_ms:
        return 1.0
    row_delay_ms = row * METRIC_VALUE_STAGGER_MS
    if value_elapsed_ms <= row_delay_ms:
        return 0.0
    return ease_out_cubic(float(value_elapsed_ms - row_delay_ms) / float(METRIC_VALUE_REVEAL_MS))


def metric_marquee_gap_px() -> int:
    return METRIC_SPACE_ADVANCE_PX * METRIC_MARQUEE_GAP_CHARS


def metric_marquee_offset_px(text: str, width_px: int, elapsed_ms: int) -> int:
    text_width = measure_metric_text(text)
    return metric_marquee_offset_for_width(text_width, width_px, elapsed_ms)


def metric_marquee_offset_for_width(text_width: int, width_px: int, elapsed_ms: int) -> int:
    if text_width <= width_px:
        return 0
    cycle_width = text_width + metric_marquee_gap_px()
    if cycle_width <= 0:
        return 0
    return int((elapsed_ms // METRIC_MARQUEE_STEP_MS) % cycle_width)


def centered_metric_text_x(x: int, width_px: int, text: str) -> int:
    text_width = measure_metric_text(text)
    if text_width >= width_px:
        return x
    return x + (width_px - text_width) // 2


def metric_contrast_for_fade_progress(progress: float) -> int:
    progress = clamp_unit_float(progress)
    remaining = 1.0 - progress
    brightness = remaining * remaining * remaining
    contrast = float(DEFAULT_OLED_CONTRAST) * brightness
    return int(contrast + 0.5)


def metric_glyph_for(char: str) -> tuple[int, ...]:
    return DOGICA_GLYPHS.get(char, DOGICA_GLYPHS["?"])


def status_glyph_for(char: str) -> tuple[int, ...]:
    return STATUS_GLYPHS.get(char, _STATUS_UNKNOWN_GLYPH)


def format_metric_line_parts(item: dict) -> tuple[str, str]:
    if "_display_title" in item:
        title = str(item.get("_display_title") or "")
    else:
        title = sanitize_display_text(str(item.get("title") or ""), MAX_TITLE_STORAGE_CHARS)
    if item.get("value_type") == "text":
        if "_display_value_text" in item:
            value = str(item.get("_display_value_text") or "")
        else:
            value = format_value_with_unit(
                sanitize_display_text(str(item.get("value") or ""), MAX_VALUE_STORAGE_CHARS),
                sanitize_display_text(str(item.get("unit") or ""), MAX_UNIT_STORAGE_CHARS),
            )
    else:
        value = ""
    return title, value


def metric_page_has_overflow(items: list[dict]) -> bool:
    for item in items[:ITEMS_PER_METRIC_PAGE]:
        title, value = format_metric_line_parts(item)
        if measure_metric_text(title) > METRIC_TITLE_WIDTH_PX:
            return True
        if item.get("value_type") == "text" and measure_metric_text(value) > METRIC_VALUE_WIDTH_PX:
            return True
    return False


def bar_current_value_text(item: dict) -> str:
    if "_display_bar_value_text" in item:
        return str(item.get("_display_bar_value_text") or "")
    return format_value_with_unit(
        format_metric_number(float(item.get("current_value") or 0.0)),
        sanitize_display_text(str(item.get("unit") or ""), MAX_UNIT_STORAGE_CHARS),
    )


def format_metric_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}".rstrip("0").rstrip(".")


@dataclass(frozen=True, slots=True)
class ColumnSprite:
    width: int
    height: int
    columns: bytes


class SketchCanvas:
    def __init__(self, width: int = OLED_WIDTH, height: int = OLED_HEIGHT):
        self.width = width
        self.height = height
        self.buffer = bytearray((width * height) // 8)
        self._clear_buffer = bytes(len(self.buffer))
        self._metric_sprite_cache: dict[str, ColumnSprite] = {}
        self._status_sprite_cache: dict[str, ColumnSprite] = {}
        self._bar_sprite_cache: dict[tuple[int, int, int], ColumnSprite] = {}

    def clear(self) -> None:
        self.buffer[:] = self._clear_buffer

    def draw_pixel(self, x: int, y: int, color: bool) -> None:
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return
        index = x + (y // 8) * self.width
        mask = 1 << (y & 7)
        if color:
            self.buffer[index] |= mask
        else:
            self.buffer[index] &= (~mask) & 0xFF

    def get_pixel(self, x: int, y: int) -> int:
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return 0
        index = x + (y // 8) * self.width
        mask = 1 << (y & 7)
        return 1 if (self.buffer[index] & mask) else 0

    @property
    def pixels(self) -> list[list[int]]:
        return [[self.get_pixel(x, y) for x in range(self.width)] for y in range(self.height)]

    def fill_rect(self, x: int, y: int, width: int, height: int, color: bool) -> None:
        for px in range(x, x + width):
            for py in range(y, y + height):
                self.draw_pixel(px, py, color)

    def draw_text_line(self, line: int, text: str) -> None:
        if line < 0 or line >= 4:
            return
        y = line * 8
        self.fill_rect(0, y, self.width, 8, False)
        upper = str(text or "").upper()
        if len(upper) > _STATUS_LINE_WIDTH:
            upper = upper[:_STATUS_LINE_WIDTH]
        self._blit_sprite(self._status_sprite(upper), 0, y)

    def draw_metric_text_clipped(
        self,
        draw_x: int,
        y: int,
        clip_left: int,
        clip_width: int,
        text: str,
        color: bool = True,
    ) -> None:
        del color
        self._blit_sprite_clipped(self._metric_sprite(text), draw_x, y, clip_left, clip_width)

    def draw_metric_text_clipped_box(
        self,
        draw_x: int,
        y: int,
        clip_left: int,
        clip_width: int,
        clip_top: int,
        clip_height: int,
        text: str,
        color: bool = True,
    ) -> None:
        del color
        self._blit_sprite_clipped(
            self._metric_sprite(text),
            draw_x,
            y,
            clip_left,
            clip_width,
            clip_top=clip_top,
            clip_height=clip_height,
        )

    def draw_metric_marquee_text(
        self,
        x: int,
        y: int,
        width_px: int,
        text: str,
        elapsed_ms: int,
        color: bool = True,
    ) -> None:
        del color
        sprite = self._metric_sprite(text)
        text_width = sprite.width
        if text_width <= width_px:
            self._blit_sprite_clipped(sprite, x, y, x, width_px)
            return
        offset_px = metric_marquee_offset_for_width(text_width, width_px, elapsed_ms)
        gap_px = metric_marquee_gap_px()
        self._blit_sprite_clipped(sprite, x - offset_px, y, x, width_px)
        self._blit_sprite_clipped(sprite, x + text_width + gap_px - offset_px, y, x, width_px)

    def draw_metric_char_window(
        self,
        x: int,
        y: int,
        char: str,
        clip_left: int,
        clip_right: int,
        clip_top: int = -32768,
        clip_bottom: int = 32767,
        color: bool = True,
    ) -> None:
        glyph = metric_glyph_for(char)
        first_col = METRIC_GLYPH_WIDTH_PX
        last_col = -1
        for col, column_bits in enumerate(glyph):
            if column_bits:
                if first_col == METRIC_GLYPH_WIDTH_PX:
                    first_col = col
                last_col = col
        if last_col < first_col:
            return
        for col in range(first_col, last_col + 1):
            screen_x = x + (col - first_col)
            if screen_x < clip_left or screen_x >= clip_right:
                continue
            column_bits = glyph[col]
            for row in range(METRIC_GLYPH_HEIGHT_PX):
                screen_y = y + row
                if screen_y < clip_top or screen_y >= clip_bottom:
                    continue
                if column_bits & (1 << row):
                    self.draw_pixel(screen_x, screen_y, color)

    def render_status(self, lines: list[str]) -> None:
        self.clear()
        for line_index in range(4):
            self.draw_text_line(line_index, lines[line_index] if line_index < len(lines) else "")

    def render_metric(self, frame: dict) -> None:
        self.clear()
        items = list(frame.get("items") or [])
        item_count = min(len(items), ITEMS_PER_METRIC_PAGE)
        title_offset_y = int(frame.get("title_offset_y") or 0)
        show_values = bool(frame.get("show_values"))
        value_elapsed_ms = int(frame.get("value_elapsed_ms") or 0)
        marquee_elapsed_ms = int(frame.get("marquee_elapsed_ms") or 0)
        hold_elapsed_ms = int(frame.get("hold_elapsed_ms") or 0)

        for row, item in enumerate(items[:ITEMS_PER_METRIC_PAGE]):
            title_label, value_text = format_metric_line_parts(item)
            row_y = _LINE_Y[row]
            dot_center_y = row_y + 3

            self.draw_metric_marquee_text(
                0,
                row_y + title_offset_y,
                METRIC_TITLE_WIDTH_PX,
                title_label,
                marquee_elapsed_ms,
                True,
            )
            if not show_values or (item.get("value_type") == "text" and not value_text):
                continue

            value_progress = metric_value_progress_for_row(item_count, row, value_elapsed_ms)
            if value_progress <= 0.0:
                continue

            final_value_x = METRIC_VALUE_START_X
            value_travel = float(OLED_WIDTH - final_value_x) * (1.0 - value_progress)
            dot_x = METRIC_DIVIDER_X + int(value_travel + 0.5)
            self.fill_rect(dot_x - 1, dot_center_y - 1, 3, 3, True)
            value_x = final_value_x + int(value_travel + 0.5)
            if item.get("value_type") == "bar":
                self.draw_alternating_bar_value(item, value_x, row_y, METRIC_VALUE_WIDTH_PX, hold_elapsed_ms)
            else:
                self.draw_metric_marquee_text(
                    value_x,
                    row_y,
                    METRIC_VALUE_WIDTH_PX,
                    value_text,
                    marquee_elapsed_ms,
                    True,
                )

    def draw_alternating_bar_value(
        self,
        item: dict,
        x: int,
        y: int,
        width_px: int,
        hold_elapsed_ms: int,
    ) -> None:
        value_row_height_px = 8
        clip_top = y
        if not item.get("show_current_value") or hold_elapsed_ms < BAR_VALUE_SWAP_MS:
            self.draw_bar_value_content(item, True, x, y, width_px, clip_top, value_row_height_px)
            return
        mode_index = hold_elapsed_ms // BAR_VALUE_SWAP_MS
        mode_elapsed_ms = hold_elapsed_ms % BAR_VALUE_SWAP_MS
        show_bar = (mode_index % 2) == 0
        if mode_elapsed_ms >= BAR_VALUE_TRANSITION_MS:
            self.draw_bar_value_content(item, show_bar, x, y, width_px, clip_top, value_row_height_px)
            return

        progress = ease_out_cubic(float(mode_elapsed_ms) / float(BAR_VALUE_TRANSITION_MS))
        previous_show_bar = not show_bar
        incoming_offset_y = int(float(value_row_height_px) * (1.0 - progress) + 0.5)
        outgoing_offset_y = int(float(value_row_height_px) * progress + 0.5)
        self.draw_bar_value_content(
            item,
            previous_show_bar,
            x,
            y - outgoing_offset_y,
            width_px,
            clip_top,
            value_row_height_px,
        )
        self.draw_bar_value_content(
            item,
            show_bar,
            x,
            y + incoming_offset_y,
            width_px,
            clip_top,
            value_row_height_px,
        )

    def draw_bar_value_content(
        self,
        item: dict,
        draw_bar: bool,
        x: int,
        y: int,
        width_px: int,
        clip_top: int,
        clip_height: int,
    ) -> None:
        if draw_bar:
            self.draw_segmented_bar(item, x, y + 1, width_px, clip_top, clip_height)
            return
        value_text = bar_current_value_text(item)
        text_x = centered_metric_text_x(x, width_px, value_text)
        self.draw_metric_text_clipped_box(text_x, y, x, width_px, clip_top, clip_height, value_text, True)

    def draw_segmented_bar(
        self,
        item: dict,
        x: int,
        y: int,
        width_px: int,
        clip_top: int,
        clip_height: int,
    ) -> None:
        sprite = self._segmented_bar_sprite(item, width_px)
        self._blit_sprite_clipped(
            sprite,
            x,
            y,
            x,
            width_px,
            clip_top=clip_top,
            clip_height=clip_height,
        )

    def _metric_sprite(self, text: str) -> ColumnSprite:
        normalized = normalize_metric_display_text(text)
        cached = self._metric_sprite_cache.get(normalized)
        if cached is not None:
            return cached

        columns = bytearray()
        for char in normalized:
            if char == DISPLAY_UNIT_GAP_PLACEHOLDER:
                columns.extend(b"\x00")
                continue

            glyph = metric_glyph_for(char)
            first_col = METRIC_GLYPH_WIDTH_PX
            last_col = -1
            for col, column_bits in enumerate(glyph):
                if column_bits:
                    if first_col == METRIC_GLYPH_WIDTH_PX:
                        first_col = col
                    last_col = col
            if last_col < first_col:
                columns.extend(b"\x00" * METRIC_SPACE_ADVANCE_PX)
                continue
            for col in range(first_col, last_col + 1):
                columns.append(glyph[col])
            columns.extend(b"\x00" * METRIC_LETTER_GAP_PX)

        if normalized and columns:
            del columns[-METRIC_LETTER_GAP_PX:]

        sprite = ColumnSprite(width=len(columns), height=METRIC_GLYPH_HEIGHT_PX, columns=bytes(columns))
        self._metric_sprite_cache[normalized] = sprite
        return sprite

    def _status_sprite(self, text: str) -> ColumnSprite:
        cached = self._status_sprite_cache.get(text)
        if cached is not None:
            return cached

        columns = bytearray()
        for char in text:
            glyph = status_glyph_for(char)
            columns.extend(glyph)
            columns.append(0)

        if text and columns:
            del columns[-1]

        sprite = ColumnSprite(width=len(columns), height=7, columns=bytes(columns))
        self._status_sprite_cache[text] = sprite
        return sprite

    def _segmented_bar_sprite(self, item: dict, width_px: int) -> ColumnSprite:
        segment_count = int(item.get("segment_count") or DEFAULT_BAR_SEGMENTS)
        if segment_count < 1:
            segment_count = DEFAULT_BAR_SEGMENTS
        elif segment_count > MAX_BAR_SEGMENTS:
            segment_count = MAX_BAR_SEGMENTS

        total_gap_width = (segment_count - 1) * BAR_SEGMENT_GAP_PX
        total_segment_width = width_px - total_gap_width
        if total_segment_width < segment_count * 2:
            return ColumnSprite(width=0, height=BAR_HEIGHT_PX, columns=b"")

        base_segment_width = total_segment_width // segment_count
        extra_pixels = total_segment_width % segment_count
        minimum = float(item.get("min_value") or 0.0)
        maximum = float(item.get("max_value") or 100.0)
        current = float(item.get("current_value") or 0.0)
        value_range = maximum - minimum
        normalized = 0.0
        if value_range > 0.0:
            normalized = clamp_unit_float((current - minimum) / value_range)
        filled_segments = int(clamp_unit_float(normalized) * segment_count + 0.5)
        cache_key = (width_px, segment_count, filled_segments)
        cached = self._bar_sprite_cache.get(cache_key)
        if cached is not None:
            return cached

        extra_left_segments = (extra_pixels + 1) // 2
        extra_right_segments = extra_pixels // 2

        full_mask = (1 << BAR_HEIGHT_PX) - 1
        middle_mask = full_mask & ~1 & ~(1 << (BAR_HEIGHT_PX - 1))
        top_bit = 1
        bottom_bit = 1 << (BAR_HEIGHT_PX - 1)
        columns = bytearray(width_px)
        write_x = 0
        for segment_index in range(segment_count):
            segment_width = base_segment_width
            if segment_index < extra_left_segments:
                segment_width += 1
            elif segment_index >= segment_count - extra_right_segments:
                segment_width += 1
            filled = segment_index < filled_segments
            round_left = segment_index == 0
            round_right = segment_index == segment_count - 1
            for rel_x in range(segment_width):
                mask = 0
                if filled:
                    mask = full_mask
                    if round_left and rel_x == 0:
                        mask &= ~top_bit
                        mask &= ~bottom_bit
                    if round_right and rel_x == segment_width - 1:
                        mask &= ~top_bit
                        mask &= ~bottom_bit
                else:
                    if rel_x == 0:
                        mask |= middle_mask
                        if not round_left:
                            mask |= top_bit | bottom_bit
                    elif rel_x == segment_width - 1:
                        mask |= middle_mask
                        if not round_right:
                            mask |= top_bit | bottom_bit
                    else:
                        mask |= top_bit | bottom_bit
                if write_x + rel_x < width_px:
                    columns[write_x + rel_x] = mask
            write_x += segment_width
            if segment_index < segment_count - 1 and write_x < width_px:
                write_x += BAR_SEGMENT_GAP_PX

        sprite = ColumnSprite(width=width_px, height=BAR_HEIGHT_PX, columns=bytes(columns))
        self._bar_sprite_cache[cache_key] = sprite
        return sprite

    def _blit_sprite(self, sprite: ColumnSprite, x: int, y: int) -> None:
        self._blit_sprite_clipped(sprite, x, y, 0, self.width, clip_top=0, clip_height=self.height)

    def _blit_sprite_clipped(
        self,
        sprite: ColumnSprite,
        draw_x: int,
        y: int,
        clip_left: int,
        clip_width: int,
        *,
        clip_top: int = 0,
        clip_height: int | None = None,
    ) -> None:
        if sprite.width <= 0 or sprite.height <= 0:
            return

        if clip_height is None:
            clip_height = self.height
        clip_right = clip_left + clip_width
        clip_bottom = clip_top + clip_height

        draw_left = max(draw_x, clip_left, 0)
        draw_right = min(draw_x + sprite.width, clip_right, self.width)
        if draw_right <= draw_left:
            return

        fully_visible_vertically = (
            y >= 0
            and (y + sprite.height) <= self.height
            and y >= clip_top
            and (y + sprite.height) <= clip_bottom
        )
        src_start = draw_left - draw_x
        src_end = src_start + (draw_right - draw_left)

        if fully_visible_vertically:
            self._blit_sprite_fast(sprite, src_start, src_end, draw_left, y)
            return

        self._blit_sprite_clipped_rows(
            sprite,
            src_start,
            src_end,
            draw_left,
            y,
            clip_top,
            clip_bottom,
        )

    def _blit_sprite_fast(
        self,
        sprite: ColumnSprite,
        src_start: int,
        src_end: int,
        draw_left: int,
        y: int,
    ) -> None:
        page = y >> 3
        shift = y & 7
        lower_base_index = page * self.width + draw_left
        upper_base_index = lower_base_index + self.width
        columns = sprite.columns

        for offset, src_index in enumerate(range(src_start, src_end)):
            column_bits = columns[src_index]
            if not column_bits:
                continue
            lower = (column_bits << shift) & 0xFF
            if lower:
                self.buffer[lower_base_index + offset] |= lower
            if shift and (page + 1) < (self.height // 8):
                upper = column_bits >> (8 - shift)
                if upper:
                    self.buffer[upper_base_index + offset] |= upper

    def _blit_sprite_clipped_rows(
        self,
        sprite: ColumnSprite,
        src_start: int,
        src_end: int,
        draw_left: int,
        y: int,
        clip_top: int,
        clip_bottom: int,
    ) -> None:
        columns = sprite.columns
        for offset, src_index in enumerate(range(src_start, src_end)):
            column_bits = columns[src_index]
            if not column_bits:
                continue
            screen_x = draw_left + offset
            for row in range(sprite.height):
                if not (column_bits & (1 << row)):
                    continue
                screen_y = y + row
                if screen_y < 0 or screen_y >= self.height:
                    continue
                if screen_y < clip_top or screen_y >= clip_bottom:
                    continue
                self.draw_pixel(screen_x, screen_y, True)

    def draw_segmented_bar_segment(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        clip_top: int,
        clip_height: int,
        filled: bool,
        round_left: bool,
        round_right: bool,
    ) -> None:
        if width <= 0 or height <= 0:
            return
        right = x + width - 1
        bottom = y + height - 1
        if filled:
            self.fill_rect_clipped(x, y, width, height, x, clip_top, width, clip_height, True)
            if round_left:
                self.fill_rect_clipped(x, y, 1, 1, x, clip_top, width, clip_height, False)
                self.fill_rect_clipped(x, bottom, 1, 1, x, clip_top, width, clip_height, False)
            if round_right:
                self.fill_rect_clipped(right, y, 1, 1, x, clip_top, width, clip_height, False)
                self.fill_rect_clipped(right, bottom, 1, 1, x, clip_top, width, clip_height, False)
            return

        top_start = x + 1 if round_left else x
        top_end = right - 1 if round_right else right
        for px in range(top_start, top_end + 1):
            self.fill_rect_clipped(px, y, 1, 1, x, clip_top, width, clip_height, True)
            self.fill_rect_clipped(px, bottom, 1, 1, x, clip_top, width, clip_height, True)
        for py in range(y + 1, bottom):
            self.fill_rect_clipped(x, py, 1, 1, x, clip_top, width, clip_height, True)
            self.fill_rect_clipped(right, py, 1, 1, x, clip_top, width, clip_height, True)

    def fill_rect_clipped(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        clip_left: int,
        clip_top: int,
        clip_width: int,
        clip_height: int,
        color: bool,
    ) -> None:
        clip_right = clip_left + clip_width
        clip_bottom = clip_top + clip_height
        draw_left = max(x, clip_left)
        draw_top = max(y, clip_top)
        draw_right = min(x + width, clip_right)
        draw_bottom = min(y + height, clip_bottom)
        if draw_right <= draw_left or draw_bottom <= draw_top:
            return
        for px in range(draw_left, draw_right):
            for py in range(draw_top, draw_bottom):
                self.draw_pixel(px, py, color)

    def _draw_text_raw(self, x: int, y: int, text: str) -> None:
        cursor_x = x
        for char in text:
            self._draw_status_char(cursor_x, y, char)
            cursor_x += 6

    def _draw_status_char(self, x: int, y: int, char: str, color: bool = True) -> None:
        glyph = status_glyph_for(char)
        for col, column_bits in enumerate(glyph):
            for row in range(7):
                if column_bits & (1 << row):
                    self.draw_pixel(x + col, y + row, color)

    def to_page_bytes(self) -> bytes:
        return bytes(self.buffer)


def _normalize_display_text(text: str, *, max_chars: int | None, placeholder_mode: bool) -> str:
    normalized: list[str] = []
    display_count = 0
    for raw_char in str(text or ""):
        mapped = _map_special_display_char(raw_char, placeholder_mode)
        if mapped is None:
            char = raw_char
            if char in {"\r", "\n", "\t", "_"}:
                char = " "
            if not is_supported_display_char(char):
                char = " "
            mapped = char
        if max_chars is not None and display_count >= max_chars:
            break
        normalized.append(mapped)
        display_count += 1
    return "".join(normalized).strip()


def _map_special_display_char(char: str, placeholder_mode: bool) -> str | None:
    if char in _DEGREE_CHARS:
        return DISPLAY_DEGREE_PLACEHOLDER if placeholder_mode else char
    if char in _OMEGA_CHARS:
        return DISPLAY_OMEGA_PLACEHOLDER if placeholder_mode else char
    return None
