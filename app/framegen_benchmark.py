"""Validate SuperRender session CSV and benchmark JSON without conflating FPS streams."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

FPS_KEYS = ("capture_fps", "presented_fps", "generated_fps")
INTERVAL_KEYS = ("wgc_frame_interval_ms_mean", "present_interval_ms_mean",
                 "present_pacing_jitter_ms")
PASS_KEYS = ("capture_copy", "motion_estimation_l0", "synthesis",
             "present_copy", "present")
ABSENT_PASS_KEYS = ("downscale_luma", "vector_refine_filter")


def _number(value, key: str):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{key}: boolean is not a number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{key}: expected nonnegative finite number")
    return number


def _check_fps(record):
    # Capture is a WGC observation, not an internal game-engine FPS counter.
    # Generated FPS is a subset of external presents, not additional real FPS.
    for key in FPS_KEYS:
        _number(record.get(key), key)
    presented = _number(record.get("presented_fps"), "presented_fps")
    generated = _number(record.get("generated_fps"), "generated_fps")
    if presented is not None and generated is not None and generated > presented + 1e-6:
        raise ValueError("generated_fps cannot exceed presented_fps")
    for key in INTERVAL_KEYS + ("engine_gpu_ms_mean",):
        _number(record.get(key), key)


def parse_session_csv(path: str | Path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"timestamp_unix_ms", "status", *FPS_KEYS, *INTERVAL_KEYS,
                    "engine_gpu_ms_mean"}
        for name in PASS_KEYS:
            required.update((f"{name}_mean_ms", f"{name}_p95_ms"))
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("missing required CSV columns")
        rows = []
        for row in reader:
            if None in row:
                raise ValueError("unexpected CSV columns")
            _check_fps(row)
            _number(row["timestamp_unix_ms"], "timestamp_unix_ms")
            for name in PASS_KEYS:
                _number(row[f"{name}_mean_ms"], name)
                _number(row[f"{name}_p95_ms"], name)
            for name in ABSENT_PASS_KEYS:
                for suffix in ("mean_ms", "p95_ms"):
                    if row.get(f"{name}_{suffix}") not in (None, ""):
                        raise ValueError(f"{name} does not exist in this pipeline")
            rows.append(row)
        return rows


def parse_benchmark_json(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        report = json.load(stream)
    if report.get("schema_version") != 1:
        raise ValueError("unsupported benchmark schema")
    _check_fps(report)
    passes = report.get("passes")
    if not isinstance(passes, dict):
        raise ValueError("missing passes object")
    for name in PASS_KEYS:
        value = passes.get(name)
        if not isinstance(value, dict):
            raise ValueError(f"missing {name} pass object")
        mean = _number(value.get("mean_ms"), f"{name}.mean_ms")
        p95 = _number(value.get("p95_ms"), f"{name}.p95_ms")
        if mean is not None and p95 is not None and p95 < mean:
            raise ValueError(f"{name}: p95 < mean")
    for name in ABSENT_PASS_KEYS:
        if passes.get(name, "missing") is not None:
            raise ValueError(f"{name} must be explicitly null")
    return report
