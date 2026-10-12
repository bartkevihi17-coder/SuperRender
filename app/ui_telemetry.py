"""Standalone lightweight Qt dashboard components for the SuperRender main UI."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .telemetry_viewmodel import TelemetryHistory
from .ui_theme import PALETTE as P


class FramePlot(QWidget):
    def __init__(self, history, parent=None):
        super().__init__(parent)
        self.history = history
        self.setMinimumHeight(145)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(P["panel"]))
        painter.setRenderHint(QPainter.Antialiasing, True)
        bounds = self.rect().adjusted(14, 12, -14, -12)
        if bounds.width() <= 5 or bounds.height() <= 5:
            return
        series = ((self.history.real, QColor(P["accent"])),
                  (self.history.output, QColor("#D9A46B")))
        values = [v for stream, _ in series for _, v in stream]
        if not values:
            painter.setPen(QColor(P["muted"]))
            painter.drawText(bounds, Qt.AlignCenter, "Aguardando frametimes válidos")
            return
        ceiling = max(33.33, min(150.0, max(values) * 1.15))
        end = max(stream[-1][0] for stream, _ in series if stream)
        for stream, shade in series:
            if len(stream) < 2:
                continue
            painter.setPen(QPen(shade, 2))
            previous = None
            for t, value in stream:
                x = bounds.right() - (end-t)/self.history.window * bounds.width()
                y = bounds.bottom() - min(value, ceiling)/ceiling * bounds.height()
                if previous is not None:
                    painter.drawLine(previous[0], previous[1], int(x), int(y))
                previous = (int(x), int(y))


class LiveTelemetryPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("telemetryPanel")
        self.setStyleSheet(f"QFrame#telemetryPanel{{background:{P['panel']};"
                           f"border:1px solid {P['stroke']};border-radius:16px;}}")
        self.history = TelemetryHistory()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16,16,16,16)
        row = QHBoxLayout()
        self.cards = {}
        for name in ("REAL", "OUTPUT", "GENERATED", "ENGINE", "LATENCY", "TIER"):
            cell = QVBoxLayout()
            title = QLabel(name)
            title.setStyleSheet(f"color:{P['muted']};font-size:10px;")
            value = QLabel("--")
            value.setStyleSheet(f"color:{P['ink']};font-size:19px;font-weight:700;")
            cell.addWidget(title)
            cell.addWidget(value)
            row.addLayout(cell)
            self.cards[name] = value
        layout.addLayout(row)
        layout.addWidget(QLabel("Frametime (30 s)   Azul: real   Âmbar: apresentado"))
        self.plot = FramePlot(self.history)
        layout.addWidget(self.plot)

    def update_data(self, timestamp, *, real_fps=None, telemetry=None,
                    real_interval_ms=None):
        metrics = TelemetryHistory.cards(real_fps, telemetry)
        for key, value in metrics.items():
            self.cards[key].setText(str(value))
        self.history.push(timestamp,
            real_interval_ms=real_interval_ms,
            output_interval_ms=(telemetry or {}).get("present_interval_ms_mean"))
        self.plot.update()
