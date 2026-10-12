"""Conservative session FG auto-tuner: independent of game-specific adapters.

A trial is valid only if it truly applied its parameters and provides observed
WGC frame intervals, presenter jitter and GPU timings. Missing quality evidence
is penalized, not silently interpreted as a perfect result.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class FGConfig:
    block_size: int
    pyramid_levels: int
    search_radius: int
    tier: int

    def __post_init__(self):
        if self.block_size not in (16, 32, 64):
            raise ValueError("unsupported block size")
        if self.pyramid_levels not in (1, 2, 3):
            raise ValueError("unsupported pyramid depth")
        if self.search_radius not in (2, 4, 8, 12):
            raise ValueError("unsupported radius")
        if not 0 <= self.tier <= 3:
            raise ValueError("invalid tier")


@dataclass(frozen=True)
class FGHardware:
    gpu: str
    game: str
    resolution: str

    def filename(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest() + ".json"


def candidates() -> tuple[FGConfig, ...]:
    return (FGConfig(32, 2, 4, 0), FGConfig(64, 2, 2, 1),
            FGConfig(32, 1, 2, 2), FGConfig(64, 1, 2, 3))


def should_retune(reference_fps: float, current_fps: float, *, threshold: float = .25) -> bool:
    if not (math.isfinite(reference_fps) and math.isfinite(current_fps)):
        return False
    if reference_fps <= 0 or current_fps <= 0:
        return False
    return abs(current_fps - reference_fps) / reference_fps >= threshold


def evaluate(config: FGConfig, *, applied: bool, engine_ms: float,
             pacing_jitter_ms: float, wgc_fps: float,
             validation_error: float | None, samples: int,
             weights: tuple[float, float, float] = (0.45, 0.20, 0.35)) -> dict:
    """Normalized objective: low cost and low motion error win.

    Validation error is expected in [0,1] for a held-out real frame B,
    estimated by synthesizing A->C at the true B timestamp.
    """
    fields = (engine_ms, pacing_jitter_ms, wgc_fps)
    if (not applied or samples < 30 or any(not math.isfinite(x) for x in fields)
            or engine_ms <= 0 or pacing_jitter_ms < 0 or wgc_fps <= 0):
        raise ValueError("invalid or unapplied trial")
    if validation_error is not None and (not math.isfinite(validation_error)
                                        or not 0 <= validation_error <= 1):
        raise ValueError("invalid visual error")
    # Missing visual validation is explicitly unscored.
    score = None if validation_error is None else (
        weights[0] * (engine_ms / max(1000.0 / wgc_fps, 1.0))
        + weights[1] * (pacing_jitter_ms / max(1000.0 / 60.0, 1.0))
        + weights[2] * validation_error
    )
    return {"config": asdict(config), "engine_ms": engine_ms,
            "pacing_jitter_ms": pacing_jitter_ms, "wgc_fps": wgc_fps,
            "validation_error": validation_error, "samples": samples,
            "score": score, "applied": True}


def select(trials: list[dict]) -> dict | None:
    valid = [t for t in trials if t.get("applied") and t.get("score") is not None]
    return min(valid, key=lambda t: t["score"]) if valid else None


def save(folder: Path, hardware: FGHardware, best: dict, *, driver: str,
         reference_fps: float) -> Path:
    if best.get("score") is None or not driver:
        raise ValueError("unvalidated trial cannot be cached")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / hardware.filename()
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"version": 1, "hardware": asdict(hardware),
                                "driver": driver, "reference_fps": reference_fps,
                                "winner": best}, indent=2), encoding="utf-8")
    os.replace(temp, path)
    return path


def load(folder: Path, hardware: FGHardware, *, driver: str,
         observed_fps: float) -> dict | None:
    try:
        data = json.loads((Path(folder) / hardware.filename()).read_text(encoding="utf-8"))
        if (data["version"] != 1 or data["hardware"] != asdict(hardware)
                or data["driver"] != driver
                or should_retune(data["reference_fps"], observed_fps)):
            return None
        return data["winner"]
    except (OSError, ValueError, TypeError, KeyError):
        return None
