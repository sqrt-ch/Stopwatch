# Stopwatch

A dark-themed desktop stopwatch built with PySide6, replicating [sqrt.ch/Buch/stopwatch](https://www.sqrt.ch/Buch/stopwatch). Supports manual start/stop/reset plus an optional microphone-triggered start/stop (e.g. clap or noise detection).

## Features

- Start / Stop / Reset with millisecond display (HH:MM:SS.mmm)
- Keyboard shortcuts: `Enter` = Start/Stop, `Esc` = Reset
- Session log with timestamped entries, Select and Clear buttons
- Optional mic-trigger mode: loud sound toggles the stopwatch, with adjustable threshold and cooldown
- Device selector with refresh button for microphone input
- WASAPI exclusive-mode audio on Windows when available, with automatic fallback to shared mode

## Requirements

- Python 3.9+
- See `requirements.txt`. The mic-trigger feature is optional — the app runs without `sounddevice`/`numpy`, just without that feature.

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
python stopwatch.py
```

## Notes

- Device list refresh forces a PortAudio re-initialization (using sounddevice's private `_terminate()`/`_initialize()`), since PortAudio caches devices at first query and won't otherwise notice hardware changes (e.g. unplugging a mic).
- Tested primarily on Windows with WASAPI; shared-mode fallback should work cross-platform.

## License

MIT-Lizenz – More Information you find here [LICENSE](LICENSE).
