"""View model for telemetry: three distinct frame streams, no synthetic values."""
from __future__ import annotations

import math
from collections import deque


class TelemetryHistory:
    def __init__(self, window_seconds=30.0):
        self.window = window_seconds
        self.real = deque()
        self.output = deque()

    @staticmethod
    def numeric(value):
        return float(value) if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 else None

    def push(self, timestamp, *, real_interval_ms=None, output_interval_ms=None):
        for series, raw in ((self.real, real_interval_ms), (self.output, output_interval_ms)):
            value = self.numeric(raw)
            if value is not None and value > 0:
                series.append((float(timestamp), value))
            while series and series[0][0] < timestamp - self.window:
                series.popleft()

    @staticmethod
    def cards(real_fps=None, telemetry=None):
        telemetry = telemetry or {}
        def display(value, unit=""):
            v = TelemetryHistory.numeric(value)
            return "--" if v is None else f"{v:.1f}{unit}"
        return {
            "REAL": display(real_fps),  # sourced from game/PresentMon, not WGC
            "OUTPUT": display(telemetry.get("presented_fps")),
            "GENERATED": display(telemetry.get("generated_fps")),
            "ENGINE": display(telemetry.get("engine_gpu_ms_mean"), " ms"),
            "LATENCY": display(telemetry.get("latency_ms"), " ms"),
            "TIER": telemetry.get("adaptive_tier", "--"),
        }
