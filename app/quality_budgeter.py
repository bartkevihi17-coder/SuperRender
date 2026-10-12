"""Generic, measurement-driven quality budgeter.

Measurements must come from the same repeatable scene and *real game* frametimes
(e.g. PresentMon). FrameGen presentation telemetry is not a substitute.
No game-specific settings or direct game file writes exist in this module.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any


@dataclass(frozen=True)
class Knob:
    name: str
    baseline: Any
    values: tuple
    visual_weights: tuple[float, ...]

    def __post_init__(self):
        if len(self.values) != len(self.visual_weights) or self.baseline not in self.values:
            raise ValueError(f"Invalid knob: {self.name}")


@dataclass(frozen=True)
class HardwareKey:
    game: str
    gpu: str
    driver: str
    resolution: str

    def filename(self) -> str:
        key = json.dumps(self.__dict__, sort_keys=True)
        return hashlib.sha256(key.encode()).hexdigest() + ".json"


def summarize_frametimes(samples: list[float]) -> dict[str, float]:
    if len(samples) < 30 or any(not math.isfinite(v) or v <= 0 for v in samples):
        raise ValueError("At least 30 positive real-game frametimes required")
    ordered = sorted(samples)
    return {
        "mean_ms": statistics.fmean(samples),
        "p95_ms": ordered[math.ceil(len(ordered) * .95) - 1],
        "samples": len(samples),
    }


def calibrate(
    knobs: tuple[Knob, ...],
    apply: Callable[[dict], None],
    measure: Callable[[float], list[float]],
    restore: Callable[[], None],
    *,
    duration_seconds: float = 12,
    baseline: dict | None = None,
) -> dict:
    """One-factor-at-a-time calibration. Caller launches/restarts replay as needed.

    apply/restore MUST go through the existing transactional config backup flow.
    The scene must be reset to an identical state by the caller for each measure.
    """
    if not 10 <= duration_seconds <= 15:
        raise ValueError("Calibration windows must be 10-15 seconds")
    baseline = dict(baseline or {k.name: k.baseline for k in knobs})
    results: dict = {}
    try:
        apply(baseline)
        reference = summarize_frametimes(measure(duration_seconds))
        for knob in knobs:
            results[knob.name] = {}
            for value in knob.values:
                try:
                    candidate = {**baseline, knob.name: value}
                    apply(candidate)
                    sample = summarize_frametimes(measure(duration_seconds))
                    delta = sample["p95_ms"] - reference["p95_ms"]
                    results[knob.name][str(value)] = {
                        **sample, "cost_ms": delta,
                        "visual_value": knob.visual_weights[knob.values.index(value)],
                    }
                finally:
                    restore()
        return {"schema_version": 1, "baseline": baseline,
                "baseline_stats": reference, "knobs": results,
                "source": "external_real_game_frametime"}
    finally:
        restore()


def solve(knobs: tuple[Knob, ...], report: dict, target_p95_ms: float) -> dict:
    """Greedy incremental multiple-choice knapsack; one option per knob.

    Costs may be negative. The report contains single-knob estimates, so
    interactions remain unmeasured and should be verified with a final replay.
    """
    if not math.isfinite(target_p95_ms) or target_p95_ms <= 0:
        raise ValueError("invalid frametime target")
    if report.get("source") != "external_real_game_frametime":
        raise ValueError("only real game frametime measurements accepted")
    base = report["baseline_stats"]["p95_ms"]
    selected = {k.name: k.baseline for k in knobs}
    current_cost = 0.0
    choices = []
    for knob in knobs:
        readings = report["knobs"][knob.name]
        low = readings[str(knob.baseline)]
        baseline_weight = knob.visual_weights[knob.values.index(knob.baseline)]
        for idx, value in enumerate(knob.values):
            if value == knob.baseline:
                continue
            entry = readings[str(value)]
            delta_cost = float(entry["cost_ms"]) - float(low["cost_ms"])
            gain = float(knob.visual_weights[idx]) - baseline_weight
            if gain > 0:
                choices.append((gain / max(delta_cost, .01), gain, delta_cost, knob.name, value))
    for _, gain, cost, name, value in sorted(choices, reverse=True):
        if selected[name] != next(k.baseline for k in knobs if k.name == name):
            continue
        if base + current_cost + cost <= target_p95_ms:
            selected[name] = value
            current_cost += cost
    return {"settings": selected, "estimated_p95_ms": base + current_cost,
            "target_p95_ms": target_p95_ms, "calibrated": True,
            "requires_combination_validation": True}


def load_cache(folder: Path, key: HardwareKey) -> dict | None:
    path = Path(folder) / key.filename()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("hardware") != key.__dict__ or data.get("schema_version") != 1:
            return None
        return data
    except (OSError, ValueError, TypeError):
        return None


def save_cache(folder: Path, key: HardwareKey, report: dict) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / key.filename()
    data = {**report, "hardware": key.__dict__}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return path
