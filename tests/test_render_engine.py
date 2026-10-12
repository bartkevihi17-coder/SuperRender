import unittest

from app.render_backend import generated_frame_count
from app.render_engine import RenderCapabilities, choose_plan


class RenderPlannerTests(unittest.TestCase):
    def test_integrated_path_wins_when_verified_and_unprotected(self):
        caps = RenderCapabilities(
            windows=True,
            executable_known=True,
            gpu_name="Test GPU",
            integrated_adapter=True,
            protected_hint=False,
            framegen_available=True,
        )
        plan = choose_plan({"name": "Offline Game"}, caps)
        self.assertEqual(plan.backend, "integrated")
        self.assertEqual(plan.reconstruction, "temporal")
        self.assertEqual(plan.target_multiplier, 4)
        self.assertTrue(plan.requires_offline)

    def test_native_dx11_framegen_when_backend_is_available(self):
        caps = RenderCapabilities(
            windows=True,
            executable_known=True,
            gpu_name="Test GPU",
            integrated_adapter=False,
            protected_hint=False,
            framegen_available=True,
        )
        plan = choose_plan({"name": "Offline Game"}, caps)
        self.assertEqual(plan.backend, "dx11-framegen")
        self.assertEqual(plan.reconstruction, "preserve-native")
        self.assertEqual(plan.frame_generation, "adaptive-2x-4x")
        self.assertTrue(plan.requires_offline)

    def test_external_fallback_does_not_fake_generation(self):
        caps = RenderCapabilities(
            windows=True,
            executable_known=True,
            gpu_name="Test GPU",
            integrated_adapter=False,
            protected_hint=False,
            framegen_available=False,
        )
        plan = choose_plan({"name": "Offline Game"}, caps)
        self.assertEqual(plan.backend, "external")
        self.assertEqual(plan.reconstruction, "preserve-native")
        self.assertEqual(plan.frame_generation, "off")

    def test_protected_hint_forces_non_invasive_light_path(self):
        caps = RenderCapabilities(
            windows=True,
            executable_known=True,
            gpu_name="Test GPU",
            integrated_adapter=True,
            protected_hint=True,
            framegen_available=True,
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
            framegen_available=True,
        )
        plan = choose_plan({"name": "Game"}, caps)
        self.assertEqual(plan.backend, "light")
        self.assertEqual(plan.frame_generation, "off")

    def test_generation_ratio_targets_60_without_claiming_real_fps(self):
        self.assertEqual(generated_frame_count(60.0), 0)
        self.assertEqual(generated_frame_count(30.0), 1)
        self.assertEqual(generated_frame_count(25.0), 2)
        self.assertEqual(generated_frame_count(22.0), 2)
        self.assertEqual(generated_frame_count(15.0), 3)


if __name__ == "__main__":
    unittest.main()
