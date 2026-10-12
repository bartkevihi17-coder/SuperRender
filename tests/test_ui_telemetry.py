import unittest

from app.telemetry_viewmodel import TelemetryHistory
from app.ui_theme import LAUNCH_STATES, PALETTE, PROFILE_DESCRIPTIONS


class TelemetryViewTests(unittest.TestCase):
    def test_fps_streams_remain_separate(self):
        cards = TelemetryHistory.cards(24, {
            "capture_fps": 22, "presented_fps": 60,
            "generated_fps": 36, "engine_gpu_ms_mean": 4.5,
            "adaptive_tier": 2,
        })
        self.assertEqual(cards["REAL"], "24.0")
        self.assertEqual(cards["OUTPUT"], "60.0")
        self.assertEqual(cards["GENERATED"], "36.0")
        self.assertEqual(cards["TIER"], 2)

    def test_unknown_never_becomes_zero(self):
        cards = TelemetryHistory.cards(None, {})
        self.assertEqual(cards["REAL"], "--")
        self.assertEqual(cards["OUTPUT"], "--")
        self.assertEqual(cards["GENERATED"], "--")

    def test_frametime_history_window(self):
        data = TelemetryHistory(30)
        data.push(0, real_interval_ms=40, output_interval_ms=17)
        data.push(31, real_interval_ms=42, output_interval_ms=18)
        self.assertEqual(list(data.real), [(31, 42)])
        self.assertEqual(list(data.output), [(31, 18)])

    def test_dark_theme_has_distinct_states(self):
        self.assertEqual(set(PROFILE_DESCRIPTIONS),
                         {"normal", "light", "optimized", "potato", "render"})
        self.assertNotEqual(LAUNCH_STATES["idle"], LAUNCH_STATES["running"])
        self.assertNotEqual(PALETTE["bg"], PALETTE["ink"])


if __name__ == "__main__":
    unittest.main()
