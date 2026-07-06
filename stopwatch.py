#!/usr/bin/env python3
"""
stopwatch.py - replicates https://www.sqrt.ch/Buch/stopwatch
Martin Ambauen with Claude AI (2026)

"""

import queue
import sys
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QElapsedTimer
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QComboBox, QSlider, QTextEdit
)

try:
    import numpy as np
    import sounddevice as sd
    MIC_AVAILABLE = True
except ImportError:
    MIC_AVAILABLE = False

MIC_COOLDOWN_MS = 600   # fading time
TICK_MS = 30            # display refresh interval, ms


def format_time(ms: float) -> str:
    """HH:MM:SS.mmm"""
    total_ms = max(0, int(ms))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def swiss_timestamp() -> str:
    """Approximates Date.toLocaleString('de-CH') for the reset log line."""
    return datetime.now().strftime("%d.%m.%Y, %H:%M:%S")


def compute_rms(samples) -> float:
    """RMS amplitude of a mono buffer scaled to [-1, 1]."""
    if len(samples) == 0:
        return 0.0
    data = np.asarray(samples, dtype=np.float64)
    return float(np.sqrt(np.mean(data ** 2)))


def is_trigger(rms: float, threshold: float, now_ms: float, last_trigger_ms: float,
               cooldown_ms: float = MIC_COOLDOWN_MS) -> bool:
    return rms > threshold and (now_ms - last_trigger_ms) > cooldown_ms

BG_MAIN = "#121212"
BG_SURFACE = "#1e1e1e"
FG_MAIN = "#ffffff"
FG_MUTED = "#aaaaaa"
BG_BTN = "#2d2d2d"
BG_BTN_ACT = "#444444"
FG_DIS = "#555555"
BTN_STYLE = f"""
QPushButton {{
    background-color: {BG_BTN};
    color: {FG_MAIN};
    border: 2px solid #555555;
    border-radius: 3px;
    font-family: Helvetica;
    font-size: 14pt;
    font-weight: bold;
    padding: 6px;
}}
QPushButton:hover {{ background-color: {BG_BTN_ACT}; }}
QPushButton:pressed {{ background-color: {BG_BTN_ACT}; }}
QPushButton:disabled {{ color: {FG_DIS}; }}
"""

MIC_BTN_STYLE = f"""
QPushButton {{
    background-color: {BG_BTN};
    color: {FG_MAIN};
    border: 2px solid #555555;
    border-radius: 3px;
    font-family: Helvetica;
    font-size: 12pt;
    font-weight: bold;
    padding: 4px 8px;
}}
QPushButton:hover {{ background-color: {BG_BTN_ACT}; }}
QPushButton:disabled {{ color: {FG_DIS}; }}
"""


class StopwatchApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stopwatch")
        self.setStyleSheet(f"background-color: {BG_MAIN};")
        self.resize(560, 500)
        self.setMinimumSize(480, 400)

        self.running = False
        self.elapsed_timer = QElapsedTimer()
        self.accumulated_ms = 0.0

        self.mic_active = False
        self.mic_stream = None
        self.last_trigger_ms = 0.0
        self.threshold_value = 0.15
        self._mic_queue = queue.Queue()

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self._tick)

        self.mic_poll_timer = QTimer(self)
        self.mic_poll_timer.timeout.connect(self._poll_mic_queue)
        self.mic_poll_timer.start(50)

        self._build_ui()

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)

        title = QLabel("Stopwatch")
        title.setStyleSheet(f"color: {FG_MAIN}; font-family: Helvetica; "
                             "font-size: 20pt; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.display = QLabel("00:00:00.000")
        self.display.setAlignment(Qt.AlignCenter)
        self.display.setStyleSheet(
            f"background-color: {BG_SURFACE}; color: {FG_MAIN}; "
            "font-family: 'Courier New'; font-size: 44pt; font-weight: bold; "
            "border: 3px solid #555555; border-radius: 4px; padding: 18px 24px;"
        )
        layout.addWidget(self.display)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop!")
        self.reset_btn = QPushButton("Reset")
        for b in (self.start_btn, self.stop_btn, self.reset_btn):
            b.setStyleSheet(BTN_STYLE)
            b.setFixedWidth(100)
            btn_row.addWidget(b)
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.reset_btn.clicked.connect(self.reset)
        btn_row.setAlignment(Qt.AlignCenter)
        layout.addLayout(btn_row)

        mic_row = QHBoxLayout()
        self.mic_btn = QPushButton("\U0001F3A4 MIC on/off")
        self.mic_btn.setStyleSheet(MIC_BTN_STYLE)
        self.mic_btn.setEnabled(MIC_AVAILABLE)
        self.mic_btn.clicked.connect(self.toggle_mic)
        mic_row.addWidget(self.mic_btn)

        self.device_map = {}  # display label -> device index
        self.device_combo = QComboBox()
        self.device_combo.setStyleSheet(
            f"background-color: {BG_BTN}; color: {FG_MAIN}; "
            "border: 2px solid #555555; border-radius: 3px; padding: 3px;"
        )
        self.device_combo.view().setStyleSheet(
            f"background-color: {BG_BTN}; color: {FG_MAIN};"
        )
        mic_row.addWidget(self.device_combo)

        self.refresh_btn = QPushButton("\u21bb")
        self.refresh_btn.setStyleSheet(MIC_BTN_STYLE)
        self.refresh_btn.setFixedWidth(36)
        self.refresh_btn.setEnabled(MIC_AVAILABLE)
        self.refresh_btn.clicked.connect(self._refresh_devices)
        mic_row.addWidget(self.refresh_btn)

        self._refresh_devices()

        thresh_label = QLabel("Threshold:")
        thresh_label.setStyleSheet(f"color: {FG_MAIN};")
        mic_row.addWidget(thresh_label)

        self.threshold_slider = QSlider(Qt.Horizontal)
        self.threshold_slider.setMinimum(1)
        self.threshold_slider.setMaximum(90)
        self.threshold_slider.setValue(int(self.threshold_value * 100))
        self.threshold_slider.setFixedWidth(180)
        self.threshold_slider.valueChanged.connect(self._on_threshold_change)
        mic_row.addWidget(self.threshold_slider)
        layout.addLayout(mic_row)

        log_row = QHBoxLayout()
        log_label = QLabel("Timer Log:")
        log_label.setStyleSheet(f"color: {FG_MAIN}; font-weight: bold; font-size: 14pt;")
        log_row.addWidget(log_label)
        log_row.addStretch()
        self.log_select_btn = QPushButton("Select")
        self.log_clear_btn = QPushButton("Clear")
        for b in (self.log_select_btn, self.log_clear_btn):
            b.setStyleSheet(MIC_BTN_STYLE)
            log_row.addWidget(b)
        self.log_select_btn.clicked.connect(self._select_log)
        self.log_clear_btn.clicked.connect(self._clear_log)
        layout.addLayout(log_row)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            f"background-color: {BG_SURFACE}; color: {FG_MAIN}; "
            "font-family: 'Courier New'; font-size: 11pt; "
            "border: 3px solid #555555; border-radius: 4px;"
        )
        layout.addWidget(self.log_text)

        info = "Keyboard:  Enter = Start/Stop    Esc = Reset"
        if not MIC_AVAILABLE:
            info += "\n(mic trigger needs: pip install sounddevice numpy)"
        info_label = QLabel(info)
        info_label.setStyleSheet(f"color: {FG_MUTED}; font-family: Helvetica; font-size: 10pt;")
        layout.addWidget(info_label)

    def _refresh_devices(self):
        if self.mic_active:
            return
        self.device_map = {}
        if MIC_AVAILABLE:
            try:
                sd._terminate()
                sd._initialize()
                for i, d in enumerate(sd.query_devices()):
                    if d.get("max_input_channels", 0) > 0:
                        self.device_map[f"{i}: {d['name']}"] = i
            except Exception:
                pass
        self.device_combo.clear()
        if self.device_map:
            self.device_combo.addItems(list(self.device_map.keys()))
            self.device_combo.setEnabled(True)
        else:
            self.device_combo.addItem("no input devices found")
            self.device_combo.setEnabled(False)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.toggle()
        elif event.key() == Qt.Key_Escape:
            self.reset()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------ core timing
    def elapsed_ms(self) -> float:
        if not self.running:
            return self.accumulated_ms
        return self.accumulated_ms + self.elapsed_timer.elapsed()

    def toggle(self):
        self.stop() if self.running else self.start()

    def start(self):
        if self.running:
            return
        self.running = True
        self.elapsed_timer.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.tick_timer.start(TICK_MS)

    def stop(self):
        if not self.running:
            return
        self.accumulated_ms = self.elapsed_ms()
        self.running = False
        self.tick_timer.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._refresh_display()
        self._log(self.display.text())

    def reset(self):
        self.tick_timer.stop()
        self.running = False
        self.accumulated_ms = 0.0
        self.display.setText("00:00:00.000")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._log("Reset")

    def _refresh_display(self):
        self.display.setText(format_time(self.elapsed_ms()))

    def _tick(self):
        self._refresh_display()

    def _log(self, line: str):
        self.log_text.append(f"[{swiss_timestamp()}] {line}")

    def _select_log(self):
        self.log_text.selectAll()
        self.log_text.setFocus()

    def _clear_log(self):
        self.log_text.clear()

    # ------------------------------------------------------- mic trigger
    def _on_threshold_change(self, value):
        self.threshold_value = value / 100.0

    def toggle_mic(self):
        self._stop_mic() if self.mic_active else self._start_mic()

    def _start_mic(self):
        if not MIC_AVAILABLE:
            return
        label = self.device_combo.currentText()
        device_idx = self.device_map.get(label)
        if device_idx is None:
            self._log("Mic error: no input device selected")
            return

        extra_settings = None
        if hasattr(sd, "WasapiSettings"):
            try:
                extra_settings = sd.WasapiSettings(exclusive=True)
            except Exception:
                extra_settings = None

        def open_stream(settings):
            return sd.InputStream(device=device_idx, channels=1, samplerate=44100,
                                   blocksize=2048, dtype="float32",
                                   callback=self._audio_callback,
                                   extra_settings=settings)

        try:
            try:
                self.mic_stream = open_stream(extra_settings)
                mode_note = " (WASAPI exclusive)" if extra_settings else ""
            except Exception:
                # exclusive mode unavailable/busy -> fall back to shared mode
                self.mic_stream = open_stream(None)
                mode_note = " (shared mode fallback)" if extra_settings else ""
            self.mic_stream.start()
            self.mic_active = True
            self.mic_btn.setText("MIC OFF")
            self.device_combo.setEnabled(False)
            self.refresh_btn.setEnabled(False)
            self._log(f"Mic started: {label}{mode_note}")
        except Exception as exc:
            self._log(f"Mic error: {exc}")

    def _stop_mic(self):
        if self.mic_stream is not None:
            self.mic_stream.stop()
            self.mic_stream.close()
            self.mic_stream = None
        self.mic_active = False
        self.mic_btn.setText("\U0001F3A4 MIC on/off")
        if self.device_map:
            self.device_combo.setEnabled(True)
        self.refresh_btn.setEnabled(MIC_AVAILABLE)

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            self._mic_queue.put(("status", str(status)))
        rms = compute_rms(indata[:, 0])
        now_ms = time.perf_counter() * 1000
        if is_trigger(rms, self.threshold_value, now_ms, self.last_trigger_ms):
            self.last_trigger_ms = now_ms
            self._mic_queue.put(("trigger", None))

    def _poll_mic_queue(self):
        try:
            while True:
                kind, payload = self._mic_queue.get_nowait()
                if kind == "trigger":
                    self.toggle()
                elif kind == "status":
                    self._log(f"Mic status: {payload}")
        except queue.Empty:
            pass

    def closeEvent(self, event):
        self.tick_timer.stop()
        self._stop_mic()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = StopwatchApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()