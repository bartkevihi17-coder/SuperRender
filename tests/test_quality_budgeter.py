"""Quality budgeter tests: fake adapter, simulated *real-game* frametimes."""
import pytest

from app.quality_budgeter import (
    Knob, HardwareKey, calibrate, load_cache, save_cache, solve,
    summarize_frametimes,
)
from app.quality_adapters import render_budgeted_changes


def fake_knobs():
    return (
        Knob("textures", "low", ("low", "high"), (0, 10)),
        Knob("fog", "off", ("off", "on"), (0, 2)),
    )


def test_calibration_restores_configuration_even_after_measurements():
    state = {}
    restored = []
    def apply(values):
        state.clear()
        state.update(values)
    def measure(seconds):
        assert seconds == 12
        delta = (1 if state["textures"] == "high" else 0) + (
            8 if state["fog"] == "on" else 0
        )
        return [20.0 + delta] * 120
    def restore():
        restored.append(True)
    result = calibrate(fake_knobs(), apply, measure, restore)
    assert result["knobs"]["textures"]["high"]["cost_ms"] == pytest.approx(1.0)
    assert result["knobs"]["fog"]["on"]["cost_ms"] == pytest.approx(8.0)
    assert len(restored) >= 5


def test_solver_prefers_high_value_per_ms():
    knobs = fake_knobs()
    state = {}
    def apply(x):
        state.update(x)
    def measure(_):
        return [20.0 + (state["textures"] == "high") +
                8 * (state["fog"] == "on")] * 120
    report = calibrate(knobs, apply, measure, lambda: None)
    solution = solve(knobs, report, 22.0)
    assert solution["settings"] == {"textures": "high", "fog": "off"}
    assert solution["requires_combination_validation"] is True


def test_cache_invalidates_driver_gpu_resolution(tmp_path):
    key = HardwareKey("game", "GT 730", "driver-1", "1280x720")
    report = {"schema_version": 1, "source": "external_real_game_frametime"}
    save_cache(tmp_path, key, report)
    assert load_cache(tmp_path, key) is not None
    assert load_cache(tmp_path, HardwareKey("game", "GT 730", "driver-2", "1280x720")) is None
    assert load_cache(tmp_path, HardwareKey("game", "GTX 750", "driver-1", "1280x720")) is None
    assert load_cache(tmp_path, HardwareKey("game", "GT 730", "driver-1", "1920x1080")) is None


def test_reject_presented_or_generated_fps_as_calibration():
    with pytest.raises(ValueError, match="real game"):
        solve(fake_knobs(), {"source": "framegen_presented_fps"}, 33.0)


def test_no_cache_no_quality_override(tmp_path):
    changes = render_budgeted_changes(
        "nba2k20", {"WIDTH": 1280, "HEIGHT": 720},
        game_id="nba", gpu="GT 730", driver="123",
        cache_dir=tmp_path,
    )
    assert changes == {}


def test_invalid_sample_rejected():
    with pytest.raises(ValueError):
        summarize_frametimes([16.0, 17.0])
