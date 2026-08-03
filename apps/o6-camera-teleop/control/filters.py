from __future__ import annotations

from typing import Iterable

import numpy as np


class CommandFilter:
    """EMA smoothing followed by deadband, clipping, and slew limiting."""

    def __init__(self, ema_alpha: float, deadband: float, max_delta: float) -> None:
        if not 0.0 < ema_alpha <= 1.0:
            raise ValueError("ema_alpha must be in (0, 1]")
        self.alpha = float(ema_alpha)
        self.deadband = max(0.0, float(deadband))
        self.max_delta = max(0.0, float(max_delta))
        self._ema: np.ndarray | None = None
        self._command: np.ndarray | None = None

    def reset(self, pose: Iterable[float] | None = None) -> None:
        if pose is None:
            self._ema = None
            self._command = None
            return
        values = self._validate(pose)
        self._ema = values.copy()
        self._command = values.copy()

    def apply(self, pose: Iterable[float]) -> list[int]:
        target = self._validate(pose)
        if self._ema is None:
            self._ema = target.copy()
            self._command = target.copy()
        else:
            self._ema = self.alpha * target + (1.0 - self.alpha) * self._ema
            delta = self._ema - self._command
            delta[np.abs(delta) < self.deadband] = 0.0
            delta = np.clip(delta, -self.max_delta, self.max_delta)
            self._command = np.clip(self._command + delta, 0.0, 255.0)
        return np.rint(self._command).astype(int).tolist()

    @staticmethod
    def _validate(pose: Iterable[float]) -> np.ndarray:
        values = np.asarray(list(pose), dtype=float)
        if values.shape != (6,) or not np.all(np.isfinite(values)):
            raise ValueError("pose must contain exactly 6 finite values")
        return np.clip(values, 0.0, 255.0)
