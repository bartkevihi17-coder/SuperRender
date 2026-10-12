import pytest

from app.fg_auto_tuner import (FGConfig, FGHardware, candidates, evaluate,
                               select, should_retune, load, save)


def trial(config, error, engine=3.0):
    return evaluate(config, applied=True, engine_ms=engine,
                    pacing_jitter_ms=1.0, wgc_fps=30.0,
                    validation_error=error, samples=90)


def test_four_distinct_candidates():
    assert len(set(candidates())) == 4


def test_score_prefers_better_visual_result_at_similar_cost():
    a = trial(candidates()[0], .30)
    b = trial(candidates()[1], .05)
    assert select([a, b]) == b


def test_unapplied_or_missing_quality_cannot_win():
    with pytest.raises(ValueError):
        evaluate(candidates()[0], applied=False, engine_ms=2,
                 pacing_jitter_ms=1, wgc_fps=30,
                 validation_error=0.1, samples=90)
    uncertain = evaluate(candidates()[0], applied=True, engine_ms=1,
                         pacing_jitter_ms=0, wgc_fps=30,
                         validation_error=None, samples=90)
    assert select([uncertain]) is None


def test_cache_and_rate_change(tmp_path):
    hardware = FGHardware("GT 730", "generic-game", "1280x720")
    best = trial(candidates()[0], .12)
    save(tmp_path, hardware, best, driver="472.12", reference_fps=30)
    assert load(tmp_path, hardware, driver="472.12", observed_fps=30) == best
    assert load(tmp_path, hardware, driver="472.13", observed_fps=30) is None
    assert load(tmp_path, hardware, driver="472.12", observed_fps=19) is None
    assert load(tmp_path, FGHardware("GT 730", "generic-game", "1920x1080"),
                driver="472.12", observed_fps=30) is None


def test_retune_hysteresis():
    assert not should_retune(30, 25)
    assert should_retune(30, 20)
    assert not should_retune(30, 0)
