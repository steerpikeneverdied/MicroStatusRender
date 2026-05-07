import io
import json
import sys
import unittest
from dataclasses import replace
from unittest.mock import patch

from microstatus_display_client.client import MicrostatusApiClient, MicrostatusClientConfig
from microstatus_display_client.display.console import ConsoleDisplay
from microstatus_display_client.display.null import NullDisplay
from microstatus_display_client.display.sketch_surface import (
    BAR_VALUE_SWAP_MS,
    DEFAULT_OLED_CONTRAST,
    DISPLAY_FRAME_INTERVAL_MS,
    ITEMS_PER_METRIC_PAGE,
    METRIC_MARQUEE_STEP_MS,
    METRIC_PAGE_HOLD_MS,
    METRIC_TITLE_SCROLL_MS,
    METRIC_VALUE_REVEAL_MS,
    METRIC_VALUE_STAGGER_MS,
    SketchCanvas,
    format_value_with_unit,
    measure_metric_text,
)
from microstatus_display_client.display.ssd1306 import DisplayInitError, SSD1306Display
from microstatus_display_client.main import DisplayRuntimeConfig, create_display_backend
from microstatus_display_client.renderer import (
    PHASE_FADE_OUT,
    PHASE_HOLD,
    PHASE_TITLE_INTRO,
    PHASE_VALUE_INTRO,
    MicrostatusRenderer,
    build_frame,
    normalize_render_payload,
)


class FakeDisplay:
    def __init__(self):
        self.frames = []

    def render_frame(self, frame):
        self.frames.append(frame)


class DisplayClientTests(unittest.TestCase):
    def test_render_payload_parsing(self):
        payload = normalize_render_payload(
            "CLEAR_OLD\n"
            "Printer\n"
            "BAR MIN=0 MAX=100 CURRENT=67 UNIT=% SHOW_VALUE=1\n"
            "Temp\n"
            "21.4 UNIT=°C\n"
        )

        frame = build_frame(payload, 0, phase=PHASE_HOLD, hold_elapsed_ms=2500)

        self.assertEqual(frame["mode"], "metric")
        self.assertEqual(frame["layout"], {"width": 128, "height": 32, "rows": ITEMS_PER_METRIC_PAGE})
        self.assertEqual(frame["items"][0]["value_type"], "bar")
        self.assertEqual(frame["items"][0]["title"], "Printer")
        self.assertTrue(frame["items"][0]["show_current_value"])
        self.assertEqual(frame["items"][0]["unit"], "%")
        self.assertEqual(frame["items"][1]["value_type"], "text")
        self.assertEqual(frame["items"][1]["value"], "21.4")
        self.assertEqual(frame["items"][1]["unit"], "°C")

    def test_empty_payload_uses_idle_metric_fallback(self):
        payload = normalize_render_payload("")
        frame = build_frame(payload, 0, phase=PHASE_HOLD, hold_elapsed_ms=0)

        self.assertEqual(frame["mode"], "metric")
        self.assertEqual(frame["items"][0]["title"], "Status")
        self.assertEqual(frame["items"][0]["value"], "Idle")

    def test_title_intro_uses_full_screen_offset_at_start(self):
        frame = build_frame("Status\nIdle\n", 0, phase=PHASE_TITLE_INTRO, phase_elapsed_ms=0)
        self.assertEqual(frame["title_offset_y"], 32)
        self.assertFalse(frame["show_values"])

    def test_renderer_transitions_match_sketch_phases(self):
        display = FakeDisplay()
        renderer = MicrostatusRenderer(display, monotonic=lambda: 0.0)
        payload = "One\n1\nTwo\n2\nThree\n3\n"
        renderer.update_payload(payload, now=0.0)

        title_frame = renderer.render_next_frame(now=0.0)
        self.assertEqual(title_frame["phase"], PHASE_TITLE_INTRO)

        value_frame = renderer.render_next_frame(now=(METRIC_TITLE_SCROLL_MS + 1) / 1000)
        self.assertEqual(value_frame["phase"], PHASE_VALUE_INTRO)
        self.assertTrue(value_frame["show_values"])

        hold_frame = renderer.render_next_frame(
            now=(METRIC_TITLE_SCROLL_MS + METRIC_VALUE_REVEAL_MS + (2 * METRIC_VALUE_STAGGER_MS) + 2) / 1000
        )
        self.assertEqual(hold_frame["phase"], PHASE_HOLD)

        renderer.render_next_frame(
            now=(
                METRIC_TITLE_SCROLL_MS
                + METRIC_VALUE_REVEAL_MS
                + (2 * METRIC_VALUE_STAGGER_MS)
                + METRIC_PAGE_HOLD_MS
                + 5
            )
            / 1000
        )
        fade_frame = renderer.render_next_frame(
            now=(
                METRIC_TITLE_SCROLL_MS
                + METRIC_VALUE_REVEAL_MS
                + (2 * METRIC_VALUE_STAGGER_MS)
                + METRIC_PAGE_HOLD_MS
                + 40
            )
            / 1000
        )
        self.assertEqual(fade_frame["phase"], PHASE_FADE_OUT)

    def test_renderer_emits_blank_frame_between_pages(self):
        display = FakeDisplay()
        renderer = MicrostatusRenderer(display, monotonic=lambda: 0.0)
        renderer.update_payload("One\n1\n", now=0.0)
        renderer.render_next_frame(now=0.0)
        renderer.render_next_frame(now=(METRIC_TITLE_SCROLL_MS + 1) / 1000)
        renderer.render_next_frame(now=(METRIC_TITLE_SCROLL_MS + METRIC_VALUE_REVEAL_MS + 2) / 1000)
        renderer.render_next_frame(
            now=(METRIC_TITLE_SCROLL_MS + METRIC_VALUE_REVEAL_MS + METRIC_PAGE_HOLD_MS + 5) / 1000
        )
        renderer.render_next_frame(
            now=(METRIC_TITLE_SCROLL_MS + METRIC_VALUE_REVEAL_MS + METRIC_PAGE_HOLD_MS + 40) / 1000
        )
        renderer.render_next_frame(
            now=(METRIC_TITLE_SCROLL_MS + METRIC_VALUE_REVEAL_MS + METRIC_PAGE_HOLD_MS + 2040) / 1000
        )
        self.assertEqual(display.frames[-1]["mode"], "blank")
        next_frame = renderer.render_next_frame(
            now=(
                METRIC_TITLE_SCROLL_MS
                + METRIC_VALUE_REVEAL_MS
                + METRIC_PAGE_HOLD_MS
                + 2040
                + 33
            )
            / 1000
        )
        self.assertEqual(next_frame["phase"], PHASE_TITLE_INTRO)

    def test_renderer_updates_visible_values_without_replacing_titles(self):
        display = FakeDisplay()
        renderer = MicrostatusRenderer(display, monotonic=lambda: 0.0)
        initial_payload = (
            "Temp\n21 UNIT=°C\n"
            "Printer\nBAR MIN=0 MAX=100 CURRENT=50 UNIT=% SHOW_VALUE=1\n"
            "Phase\nPrinting\n"
        )
        renderer.update_payload(initial_payload, now=0.0)
        hold_time = (METRIC_TITLE_SCROLL_MS + METRIC_VALUE_REVEAL_MS + (2 * METRIC_VALUE_STAGGER_MS) + 2) / 1000
        renderer.render_next_frame(now=0.0)
        renderer.render_next_frame(now=(METRIC_TITLE_SCROLL_MS + 1) / 1000)
        renderer.render_next_frame(now=hold_time)

        updated_payload = (
            "Temp\n22 UNIT=°C\n"
            "Printer\nBAR MIN=0 MAX=100 CURRENT=55 UNIT=% SHOW_VALUE=1\n"
            "Phase\nCooling\n"
            "Queue\n3\n"
        )
        renderer.update_payload(updated_payload, now=hold_time)
        frame = renderer.render_next_frame(now=hold_time)

        self.assertEqual(frame["phase"], PHASE_HOLD)
        self.assertEqual([item["title"] for item in frame["items"]], ["Temp", "Printer", "Phase"])
        self.assertEqual(frame["items"][0]["value"], "22")
        self.assertEqual(frame["items"][1]["current_value"], 55.0)
        self.assertEqual(frame["items"][2]["value"], "Cooling")

    def test_renderer_defers_new_titles_until_next_page_transition(self):
        display = FakeDisplay()
        renderer = MicrostatusRenderer(display, monotonic=lambda: 0.0)
        initial_payload = "Temp\n21\nPrinter\nOK\nPhase\nPrinting\n"
        renderer.update_payload(initial_payload, now=0.0)
        hold_time = (METRIC_TITLE_SCROLL_MS + METRIC_VALUE_REVEAL_MS + (2 * METRIC_VALUE_STAGGER_MS) + 2) / 1000
        renderer.render_next_frame(now=0.0)
        renderer.render_next_frame(now=(METRIC_TITLE_SCROLL_MS + 1) / 1000)
        renderer.render_next_frame(now=hold_time)

        updated_payload = "Temp\n22\nPrinter\nOK\nPhase\nCooling\nQueue\n3\n"
        renderer.update_payload(updated_payload, now=hold_time)
        current_frame = renderer.render_next_frame(now=hold_time)
        self.assertEqual([item["title"] for item in current_frame["items"]], ["Temp", "Printer", "Phase"])

        fade_start = hold_time + (METRIC_PAGE_HOLD_MS + 5) / 1000
        renderer.render_next_frame(now=fade_start)
        renderer.render_next_frame(now=fade_start + 0.035)
        renderer.render_next_frame(now=fade_start + 2.035)
        next_frame = renderer.render_next_frame(
            now=fade_start + 2.068
        )

        self.assertEqual(next_frame["phase"], PHASE_TITLE_INTRO)
        self.assertEqual([item["title"] for item in next_frame["items"]], ["Queue"])

    def test_static_hold_page_does_not_redraw_every_frame(self):
        display = FakeDisplay()
        renderer = MicrostatusRenderer(display, monotonic=lambda: 0.0)
        payload = "Temp\n21\nPrinter\nReady\nPhase\nIdle\n"
        renderer.update_payload(payload, now=0.0)
        hold_time = (METRIC_TITLE_SCROLL_MS + METRIC_VALUE_REVEAL_MS + (2 * METRIC_VALUE_STAGGER_MS) + 2) / 1000

        renderer.render_next_frame(now=0.0)
        renderer.render_next_frame(now=(METRIC_TITLE_SCROLL_MS + 1) / 1000)
        renderer.render_next_frame(now=hold_time)
        frame_count_at_hold = len(display.frames)

        renderer.render_next_frame(now=hold_time + 0.033)
        renderer.render_next_frame(now=hold_time + 0.066)

        self.assertEqual(len(display.frames), frame_count_at_hold)

    def test_static_hold_page_schedules_next_page_transition_without_frame_polling(self):
        display = FakeDisplay()
        renderer = MicrostatusRenderer(display, monotonic=lambda: 0.0)
        payload = "Temp\n21\nPrinter\nReady\nPhase\nIdle\n"
        renderer.update_payload(payload, now=0.0)
        hold_time = (METRIC_TITLE_SCROLL_MS + METRIC_VALUE_REVEAL_MS + (2 * METRIC_VALUE_STAGGER_MS) + 2) / 1000

        renderer.render_next_frame(now=0.0)
        renderer.render_next_frame(now=(METRIC_TITLE_SCROLL_MS + 1) / 1000)
        renderer.render_next_frame(now=hold_time)

        self.assertGreater(renderer.next_frame_delay_seconds(now=hold_time), 9.9)

    def test_hold_page_redraws_only_when_marquee_step_changes(self):
        display = FakeDisplay()
        renderer = MicrostatusRenderer(display, monotonic=lambda: 0.0)
        payload = (
            "Current Print Queue Name That Should Scroll\n"
            "south-kitchen-production-queue-alpha-very-long-name\n"
            "Printer\nReady\n"
            "Phase\nIdle\n"
        )
        renderer.update_payload(payload, now=0.0)
        hold_time = (METRIC_TITLE_SCROLL_MS + METRIC_VALUE_REVEAL_MS + (2 * METRIC_VALUE_STAGGER_MS) + 2) / 1000

        renderer.render_next_frame(now=0.0)
        renderer.render_next_frame(now=(METRIC_TITLE_SCROLL_MS + 1) / 1000)
        renderer.render_next_frame(now=hold_time)
        frame_count_at_hold = len(display.frames)

        renderer.render_next_frame(now=hold_time + ((METRIC_MARQUEE_STEP_MS - 10) / 1000.0))
        self.assertEqual(len(display.frames), frame_count_at_hold)

        renderer.render_next_frame(now=hold_time + ((METRIC_MARQUEE_STEP_MS + 10) / 1000.0))
        self.assertEqual(len(display.frames), frame_count_at_hold + 1)

    def test_overflow_hold_schedules_marquee_cadence(self):
        display = FakeDisplay()
        renderer = MicrostatusRenderer(display, monotonic=lambda: 0.0)
        payload = (
            "Current Print Queue Name That Should Scroll\n"
            "south-kitchen-production-queue-alpha-very-long-name\n"
            "Printer\nReady\n"
            "Phase\nIdle\n"
        )
        renderer.update_payload(payload, now=0.0)
        hold_time = (METRIC_TITLE_SCROLL_MS + METRIC_VALUE_REVEAL_MS + (2 * METRIC_VALUE_STAGGER_MS) + 2) / 1000

        renderer.render_next_frame(now=0.0)
        renderer.render_next_frame(now=(METRIC_TITLE_SCROLL_MS + 1) / 1000)
        renderer.render_next_frame(now=hold_time)

        self.assertAlmostEqual(
            renderer.next_frame_delay_seconds(now=hold_time),
            METRIC_MARQUEE_STEP_MS / 1000.0,
            places=3,
        )

    def test_bar_value_swap_sleeps_until_transition_window(self):
        display = FakeDisplay()
        renderer = MicrostatusRenderer(display, monotonic=lambda: 0.0)
        payload = "Printer\nBAR MIN=0 MAX=100 CURRENT=50 UNIT=% SHOW_VALUE=1\n"
        renderer.update_payload(payload, now=0.0)
        hold_time = (METRIC_TITLE_SCROLL_MS + METRIC_VALUE_REVEAL_MS + 2) / 1000

        renderer.render_next_frame(now=0.0)
        renderer.render_next_frame(now=(METRIC_TITLE_SCROLL_MS + 1) / 1000)
        renderer.render_next_frame(now=hold_time)

        self.assertAlmostEqual(
            renderer.next_frame_delay_seconds(now=hold_time),
            BAR_VALUE_SWAP_MS / 1000.0,
            places=3,
        )
        self.assertAlmostEqual(
            renderer.next_frame_delay_seconds(now=hold_time + (BAR_VALUE_SWAP_MS + 1) / 1000.0),
            DISPLAY_FRAME_INTERVAL_MS / 1000.0,
            places=3,
        )

    def test_status_canvas_renders_expected_pixels(self):
        canvas = SketchCanvas()
        canvas.render_status(["Status", "Idle", "", ""])
        self.assertTrue(any(pixel for pixel in canvas.pixels[0][:20]))
        self.assertTrue(any(pixel for pixel in canvas.pixels[8][:20]))

    def test_metric_measurement_uses_unit_gap_placeholder(self):
        compact = measure_metric_text(format_value_with_unit("21.4", "°C"))
        spaced = measure_metric_text("21.4 °C")
        self.assertLess(compact, spaced)

    def test_disconnected_server_fallback(self):
        display = FakeDisplay()
        renderer = MicrostatusRenderer(display)

        frame = renderer.render_disconnected("connection refused")

        self.assertEqual(frame["mode"], "status")
        self.assertEqual(frame["lines"][1], "DISCONNECTED")
        self.assertEqual(frame["lines"][2], "RETRYING")

    def test_console_and_null_display_modes(self):
        config = DisplayRuntimeConfig(
            api_base="http://127.0.0.1:18100",
            display_id="display-1",
            display_name="Display One",
            location=None,
            poll_interval=1.0,
            mode="console",
            auth_token=None,
            heartbeat_interval=10.0,
            i2c_bus=1,
            oled_address=0x3C,
            oled_width=128,
            oled_height=32,
            rows=3,
        )

        self.assertIsInstance(create_display_backend(config), ConsoleDisplay)
        self.assertIsInstance(create_display_backend(replace(config, mode="null")), NullDisplay)

    def test_oled_init_failure_falls_back_to_console(self):
        config = DisplayRuntimeConfig(
            api_base="http://127.0.0.1:18100",
            display_id="display-1",
            display_name="Display One",
            location=None,
            poll_interval=1.0,
            mode="auto",
            auth_token=None,
            heartbeat_interval=10.0,
            i2c_bus=1,
            oled_address=0x3C,
            oled_width=128,
            oled_height=32,
            rows=3,
        )

        with patch("microstatus_display_client.main.SSD1306Display", side_effect=DisplayInitError("no oled")):
            backend = create_display_backend(config)

        self.assertIsInstance(backend, ConsoleDisplay)

    def test_oled_runtime_write_error_triggers_recovery_without_raising(self):
        display = SSD1306Display.__new__(SSD1306Display)
        display._render_attempts = 0

        def fake_render_frame_impl(frame):
            del frame
            display._render_attempts += 1
            if display._render_attempts == 1:
                raise TimeoutError("i2c timeout")

        display._render_frame_impl = fake_render_frame_impl
        display._recover_from_io_error = lambda exc: True

        display.render_frame({"mode": "status", "lines": ["A", "B", "C", "D"]})

        self.assertEqual(display._render_attempts, 2)

    def test_oled_skips_unchanged_pages_and_updates_only_dirty_pages(self):
        class _FakeBus:
            def __init__(self):
                self.calls = []

            def i2c_rdwr(self, *messages):
                self.calls.append(messages)

        class _FakeI2CMsg:
            @staticmethod
            def write(address, data):
                return (address, bytes(data))

        display = SSD1306Display.__new__(SSD1306Display)
        display._address = 0x3C
        display.width = 128
        display.height = 32
        display._page_count = 4
        display._canvas = SketchCanvas()
        display._bus = _FakeBus()
        display._i2c_msg = _FakeI2CMsg()
        display._page_setup_packets = tuple(bytes([0x00, 0xB0 | page, 0x00, 0x10]) for page in range(4))
        display._page_data_buffers = [bytearray(129) for _ in range(4)]
        for buffer in display._page_data_buffers:
            buffer[0] = 0x40
        display._last_sent_pages = [None] * 4

        display._display_canvas()
        self.assertEqual(len(display._bus.calls), 4)

        display._display_canvas()
        self.assertEqual(len(display._bus.calls), 4)

        display._canvas.draw_pixel(0, 0, True)
        display._display_canvas()
        self.assertEqual(len(display._bus.calls), 5)

    def test_oled_blank_frame_disables_panel_without_data_rewrite(self):
        display = SSD1306Display.__new__(SSD1306Display)
        display._canvas = SketchCanvas()
        display._contrast = DEFAULT_OLED_CONTRAST
        display._display_enabled = True
        display._page_count = 4
        display._last_sent_pages = [b"x"] * 4
        commands = []
        data_writes = []
        display._write_command_list = lambda command_bytes: commands.append(command_bytes)
        display._display_canvas = lambda: data_writes.append(True)

        display._render_frame_impl({"mode": "blank", "enabled": False})

        self.assertEqual(commands, [bytes([0xAE])])
        self.assertEqual(data_writes, [])
        self.assertEqual(display._last_sent_pages, [None] * 4)

    def test_console_display_renders_stable_output(self):
        console = ConsoleDisplay()
        frame = {
            "mode": "metric",
            "phase": "hold",
            "items": [
                {"value_type": "text", "title": "Temp", "value": "21.4", "unit": "°C"},
                {"value_type": "bar", "title": "Printer", "min_value": 0, "max_value": 100, "current_value": 50},
            ],
        }
        captured = io.StringIO()
        previous_stdout = sys.stdout
        sys.stdout = captured
        try:
            console.render_frame(frame)
            console.render_frame(frame)
        finally:
            sys.stdout = previous_stdout

        self.assertIn("Temp: 21.4 °C", captured.getvalue())
        self.assertEqual(captured.getvalue().count("Temp: 21.4 °C"), 1)

    def test_api_client_fetches_plain_render_body(self):
        config = MicrostatusClientConfig(
            api_base="http://127.0.0.1:18100",
            display_id="display-1",
            display_name="Display One",
        )
        client = MicrostatusApiClient(config)

        class _FakeResponse:
            def read(self):
                return b"CLEAR_OLD\nStatus\nIdle\n"

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("microstatus_display_client.client.request.urlopen", return_value=_FakeResponse()):
            body = client.fetch_render_body()

        self.assertEqual(body, "CLEAR_OLD\nStatus\nIdle\n")

    def test_api_client_lists_sections(self):
        config = MicrostatusClientConfig(
            api_base="http://127.0.0.1:18100",
            display_id="display-1",
            display_name="Display One",
        )
        client = MicrostatusApiClient(config)

        class _FakeResponse:
            def read(self):
                return b'[{"key": "print-status", "name": "Print status"}]'

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("microstatus_display_client.client.request.urlopen", return_value=_FakeResponse()):
            sections = client.list_sections()

        self.assertEqual(sections[0]["key"], "print-status")

    def test_api_client_subscribes_display_to_sections(self):
        config = MicrostatusClientConfig(
            api_base="http://127.0.0.1:18100",
            display_id="desk oled",
            display_name="Desk OLED",
        )
        client = MicrostatusApiClient(config)
        captured = {}

        class _FakeResponse:
            def read(self):
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse()

        with patch("microstatus_display_client.client.request.urlopen", side_effect=fake_urlopen):
            client.subscribe_display_to_sections(
                section_keys=["docker-health", "print-status"],
                layout={"rows": 3},
            )

        self.assertEqual(captured["url"], "http://127.0.0.1:18100/microstatus/displays/desk%20oled/subscriptions")
        self.assertEqual(captured["body"]["section_keys"], ["docker-health", "print-status"])
        self.assertEqual(captured["body"]["layout_json"], {"rows": 3})


if __name__ == "__main__":
    unittest.main()
