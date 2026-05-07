import unittest
from unittest.mock import patch

from microstatus_display_client.feed_setup import existing_config_value, merged_env_body, parse_section_selection


class FeedSetupTests(unittest.TestCase):
    def test_parse_section_selection_accepts_numbers_and_all(self):
        self.assertEqual(parse_section_selection("1 3", 3), [0, 2])
        self.assertEqual(parse_section_selection("2,1,2", 3), [1, 0])
        self.assertEqual(parse_section_selection("all", 3), [0, 1, 2])

    def test_parse_section_selection_rejects_out_of_range_values(self):
        with self.assertRaises(ValueError):
            parse_section_selection("4", 3)

    def test_merged_env_body_preserves_existing_values_and_appends_new_ones(self):
        body = merged_env_body(
            "MICROSTATUS_API_BASE=http://old:18100\nMICROSTATUS_POLL_INTERVAL=2\n",
            {
                "MICROSTATUS_API_BASE": "http://new:18100",
                "MICROSTATUS_SELECTED_SECTIONS": "docker-health,print-status",
            },
        )

        self.assertIn("MICROSTATUS_API_BASE=http://new:18100\n", body)
        self.assertIn("MICROSTATUS_POLL_INTERVAL=2\n", body)
        self.assertIn("MICROSTATUS_SELECTED_SECTIONS=docker-health,print-status\n", body)

    def test_existing_config_value_prefers_saved_env_file_over_process_env(self):
        with patch.dict("os.environ", {"MICROSTATUS_DISPLAY_ID": "stale-shell-id"}):
            value = existing_config_value(
                None,
                {"MICROSTATUS_DISPLAY_ID": "rack-oled-print"},
                ["MICROSTATUS_DISPLAY_ID"],
                env_var="MICROSTATUS_DISPLAY_ID",
                fallback="host-oled",
            )

        self.assertEqual(value, "rack-oled-print")

    def test_existing_config_value_prefers_explicit_value_and_supports_aliases(self):
        self.assertEqual(
            existing_config_value(
                "cli-id",
                {"DISPLAY_ID": "saved-id"},
                ["MICROSTATUS_DISPLAY_ID", "DISPLAY_ID"],
                env_var="MICROSTATUS_DISPLAY_ID",
            ),
            "cli-id",
        )
        self.assertEqual(
            existing_config_value(
                None,
                {"DISPLAY_LOCATION": "Rack"},
                ["MICROSTATUS_DISPLAY_LOCATION", "DISPLAY_LOCATION"],
                fallback="host",
            ),
            "Rack",
        )


if __name__ == "__main__":
    unittest.main()
