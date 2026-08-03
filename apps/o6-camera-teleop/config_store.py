from __future__ import annotations

import math
import os
from pathlib import Path
import tempfile
import threading

import yaml


_CONFIG_WRITE_LOCK = threading.Lock()


def save_contact_depth(path: str | Path, value: float | None) -> None:
    """Atomically update only the LiDAR contact-plane calibration."""
    config_path = Path(path).expanduser().resolve()
    contact_depth = _contact_depth(value)

    with _CONFIG_WRITE_LOCK:
        with config_path.open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
        if not isinstance(config, dict):
            raise ValueError("configuration root must be a mapping")
        lidar = config.setdefault("iphone_lidar", {})
        if not isinstance(lidar, dict):
            raise ValueError("iphone_lidar configuration must be a mapping")
        lidar["contact_depth_mm"] = contact_depth

        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=config_path.parent,
                prefix=f".{config_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                yaml.safe_dump(config, temporary, allow_unicode=True, sort_keys=False)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, config_path)
            temporary_name = None
            directory_fd = os.open(config_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass


def _contact_depth(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("contact depth must be a positive finite number or null")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("contact depth must be a positive finite number or null")
    return number
