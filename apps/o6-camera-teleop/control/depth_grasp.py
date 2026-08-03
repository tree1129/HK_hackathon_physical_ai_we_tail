from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from numbers import Real


class DepthPhase(str, Enum):
    DEPTH_UNAVAILABLE = "DEPTH_UNAVAILABLE"
    OUTSIDE_OPEN_ZONE = "OUTSIDE_OPEN_ZONE"
    PREGRASP_OPEN = "PREGRASP_OPEN"
    CONTACT_CONFIRMED = "CONTACT_CONFIRMED"


@dataclass(frozen=True)
class DepthDecision:
    phase: DepthPhase
    should_open: bool
    contact_confirmed: bool
    stable_count: int


class DepthGraspGate:
    def __init__(
        self,
        open_threshold_mm: float,
        contact_threshold_mm: float,
        stable_frames: int,
    ) -> None:
        self.open_threshold_mm = self._validated_threshold(
            open_threshold_mm, "open_threshold_mm"
        )
        self.contact_threshold_mm = self._validated_threshold(
            contact_threshold_mm, "contact_threshold_mm"
        )
        if self.open_threshold_mm <= self.contact_threshold_mm:
            raise ValueError("open_threshold_mm must exceed contact_threshold_mm")
        if isinstance(stable_frames, bool) or not isinstance(stable_frames, int):
            raise TypeError("stable_frames must be an int")
        if stable_frames < 1:
            raise ValueError("stable_frames must be at least 1")
        self.stable_frames = stable_frames
        self.stable_count = 0

    def reset(self) -> None:
        self.stable_count = 0

    def update(
        self, distance: float | None, *, armed: bool, hand_blocked: bool
    ) -> DepthDecision:
        if (
            distance is None
            or isinstance(distance, bool)
            or not isinstance(distance, Real)
            or not isfinite(distance)
            or not armed
            or hand_blocked
        ):
            self.reset()
            return self._decision(DepthPhase.DEPTH_UNAVAILABLE)

        if distance > self.open_threshold_mm:
            self.reset()
            return self._decision(DepthPhase.OUTSIDE_OPEN_ZONE)

        if distance > self.contact_threshold_mm:
            self.reset()
            return self._decision(DepthPhase.PREGRASP_OPEN, should_open=True)

        self.stable_count = min(self.stable_count + 1, self.stable_frames)
        if self.stable_count < self.stable_frames:
            return self._decision(DepthPhase.PREGRASP_OPEN, should_open=True)
        return self._decision(
            DepthPhase.CONTACT_CONFIRMED,
            should_open=True,
            contact_confirmed=True,
        )

    def _decision(
        self,
        phase: DepthPhase,
        *,
        should_open: bool = False,
        contact_confirmed: bool = False,
    ) -> DepthDecision:
        return DepthDecision(phase, should_open, contact_confirmed, self.stable_count)

    @staticmethod
    def _validated_threshold(value: float, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError(f"{name} must be a finite number")
        if not isfinite(value):
            raise ValueError(f"{name} must be finite")
        return float(value)
