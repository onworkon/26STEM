from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = {
    "host": "0.0.0.0",
    "port": 8000,
    "data_dir": "data",
    "admin_pin": "",
    "camera": {"mode": "mock", "preview_mjpeg_url": "", "snapshot_jpeg_url": "", "snapshot_method": "GET", "usb_index": 0},
    "remote": {"port": "", "baudrate": 115200},
    "printer": {"mode": "mock", "name": ""},
    "capture_delay_seconds": 0,
}


def load_config(path: Path | None = None) -> dict:
    result = deepcopy(DEFAULTS)
    config_path = path or Path(os.environ.get("STEM_CONFIG", ROOT / "config.yaml"))
    if config_path.exists():
        value = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(value, dict):
            raise ValueError("Configuration must be a YAML mapping")
        for key, item in value.items():
            if key not in result:
                raise ValueError(f"Unknown configuration field: {key}")
            if isinstance(result[key], dict):
                if not isinstance(item, dict) or set(item) - set(result[key]):
                    raise ValueError(f"Invalid configuration section: {key}")
                result[key].update(item)
            else:
                result[key] = item
    data = Path(result["data_dir"])
    result["data_dir"] = str((ROOT / data).resolve() if not data.is_absolute() else data.resolve())
    return result
