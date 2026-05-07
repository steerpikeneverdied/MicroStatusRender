import unittest

from microstatus_display_client.feed_setup import merged_env_body, parse_section_selection


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


if __name__ == "__main__":
    unittest.main()
