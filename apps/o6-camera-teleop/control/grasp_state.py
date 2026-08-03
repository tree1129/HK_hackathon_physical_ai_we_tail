from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import hypot


class GraspState(str, Enum):
    DISARMED = "DISARMED"
    ARMED = "ARMED"
    CLOSING = "CLOSING"
    HOLDING = "HOLDING"


@dataclass(frozen=True)
class TargetObservation:
    label: str
    score: float
    center_x: float
    center_y: float
    area_ratio: float


class GraspStateMachine:
    def __init__(
        self,
        grasp_zone: tuple[float, float, float, float],
        min_area_ratio: float,
        max_area_ratio: float,
        stable_frames: int,
        center_tolerance: float,
        auto_arm: bool = False,
    ) -> None:
        x1, y1, x2, y2 = grasp_zone
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError("grasp_zone must be normalized as x1,y1,x2,y2")
        if not (0 <= min_area_ratio < max_area_ratio <= 1):
            raise ValueError("invalid object area limits")
        if stable_frames < 1 or center_tolerance <= 0:
            raise ValueError("invalid stability settings")
        self.grasp_zone = grasp_zone
        self.min_area_ratio = float(min_area_ratio)
        self.max_area_ratio = float(max_area_ratio)
        self.stable_frames = int(stable_frames)
        self.center_tolerance = float(center_tolerance)
        self.state = GraspState.ARMED if auto_arm else GraspState.DISARMED
        self.stable_count = 0
        self.target: TargetObservation | None = None

    def arm(self) -> None:
        if self.state in (GraspState.DISARMED, GraspState.ARMED):
            self.state = GraspState.ARMED
            self.stable_count = 0
            self.target = None

    def disarm(self) -> None:
        if self.state != GraspState.HOLDING:
            self.state = GraspState.DISARMED
            self.stable_count = 0
            self.target = None

    def update(self, observation: TargetObservation | None) -> GraspState:
        if self.state != GraspState.ARMED:
            return self.state
        if observation is None or not self._eligible(observation):
            self.stable_count = 0
            self.target = None
            return self.state

        same_target = (
            self.target is not None
            and observation.label == self.target.label
            and hypot(
                observation.center_x - self.target.center_x,
                observation.center_y - self.target.center_y,
            )
            <= self.center_tolerance
        )
        self.stable_count = self.stable_count + 1 if same_target else 1
        self.target = observation
        if self.stable_count >= self.stable_frames:
            self.state = GraspState.CLOSING
        return self.state

    def mark_closed(self) -> None:
        if self.state == GraspState.CLOSING:
            self.state = GraspState.HOLDING

    def reset_after_open(self) -> None:
        self.state = GraspState.DISARMED
        self.stable_count = 0
        self.target = None

    @property
    def progress(self) -> float:
        return min(1.0, self.stable_count / self.stable_frames)

    def _eligible(self, observation: TargetObservation) -> bool:
        x1, y1, x2, y2 = self.grasp_zone
        return (
            x1 <= observation.center_x <= x2
            and y1 <= observation.center_y <= y2
            and self.min_area_ratio <= observation.area_ratio <= self.max_area_ratio
        )
