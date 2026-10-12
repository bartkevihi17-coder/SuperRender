import csv
import json

import pytest

from app.framegen_benchmark import (
    ABSENT_PASS_KEYS, PASS_KEYS, parse_benchmark_json, parse_session_csv,
)


def example():
    passes = {
        name: {"mean_ms": 0.5, "p95_ms": 0.8} for name in PASS_KEYS
    }
    passes.update({name: None for name in ABSENT_PASS_KEYS})
    return {
        "schema_version": 1, "status": "completed",
        "capture_fps": 24.0, "presented_fps": 60.0, "generated_fps": 36.0,
        "wgc_frame_interval_ms_mean": 41.7,
        "present_interval_ms_mean": 16.7,
        "present_pacing_jitter_ms": 1.2,
        "engine_gpu_ms_mean": 2.5, "passes": passes,
    }


def test_benchmark_keeps_fps_streams_distinct(tmp_path):
    source = tmp_path / "report.json"
    source.write_text(json.dumps(example()), encoding="utf-8")
    result = parse_benchmark_json(source)
    assert result["capture_fps"] == 24
    assert result["presented_fps"] == 60
    assert result["generated_fps"] == 36


def test_benchmark_rejects_impossible_generated_fps(tmp_path):
    data = example()
    data["generated_fps"] = 61.0
    source = tmp_path / "report.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="generated_fps"):
        parse_benchmark_json(source)


def test_benchmark_rejects_missing_luma_measurement(tmp_path):
    data = example()
    del data["passes"]["downscale_luma"]
    source = tmp_path / "report.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="downscale_luma"):
        parse_benchmark_json(source)


def test_csv_parser_keeps_metrics_separate(tmp_path):
    source = tmp_path / "session.csv"
    data = example()
    row = {key: value for key, value in data.items() if key not in ("passes", "schema_version")}
    row["timestamp_unix_ms"] = 1791750000000
    for name, metrics in data["passes"].items():
        for suffix in ("mean_ms", "p95_ms"):
            row[f"{name}_{suffix}"] = "" if metrics is None else metrics[suffix]
    with source.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        writer.writeheader()
        writer.writerow(row)
    assert parse_session_csv(source)[0]["generated_fps"] == "36.0"
