import unittest

from app.render_engine import RenderCapabilities, choose_plan


class RenderPlannerTests(unittest.TestCase):
    def test_integrated_path_wins_when_verified_and_unprotected(self):
        caps = RenderCapabilities(
            windows=True,
            executable_known=True,
            gpu_name="Test GPU",
            integrated_adapter=True,
            protected_hint=False,
        )
        plan = choose_plan({"name": "Offline Game"}, caps)
        self.assertEqual(plan.backend, "integrated")
        self.assertEqual(plan.reconstruction, "temporal")
        self.assertEqual(plan.target_multiplier, 2)
        self.assertTrue(plan.requires_offline)

    def test_external_path_for_known_executable_without_adapter(self):
        caps = RenderCapabilities(
            windows=True,
            executable_known=True,
            gpu_name="Test GPU",
            integrated_adapter=False,
            protected_hint=False,
        )
        plan = choose_plan({"name": "Offline Game"}, caps)
        self.assertEqual(plan.backend, "external")
        self.assertEqual(plan.reconstruction, "spatial-adaptive")
        self.assertEqual(plan.target_multiplier, 2)

    def test_protected_hint_forces_non_invasive_light_path(self):
        caps = RenderCapabilities(
            windows=True,
            executable_known=True,
            gpu_name="Test GPU",
            integrated_adapter=True,
            protected_hint=True,
        )
        plan = choose_plan({"name": "Competitive Game"}, caps)
        self.assertEqual(plan.backend, "light")
        self.assertEqual(plan.frame_generation, "off")
        self.assertEqual(plan.target_multiplier, 1)

    def test_non_windows_uses_light_path(self):
        caps = RenderCapabilities(
            windows=False,
            executable_known=True,
            gpu_name="Test GPU",
            integrated_adapter=True,
            protected_hint=False,
        )
        plan = choose_plan({"name": "Game"}, caps)
        self.assertEqual(plan.backend, "light")
        self.assertEqual(plan.frame_generation, "off")


if __name__ == "__main__":
    unittest.main()
