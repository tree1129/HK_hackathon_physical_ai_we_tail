from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConsoleMode(str, Enum):
    HAND_FOLLOW = "hand-follow"
    OBJECT_GRASP = "object-grasp"


class VisionSource(str, Enum):
    MAC_CAMERA = "mac-camera"
    MOBILE_CAMERA = "mobile-camera"
    IPHONE_LIDAR = "iphone-lidar"


class TrackingState(str, Enum):
    WAITING_HAND = "WAITING_HAND"
    TRACKING = "TRACKING"
    HOLDING_LAST = "HOLDING_LAST"
    PAUSED_LOST = "PAUSED_LOST"


@dataclass
class ConsoleModeState:
    mode: ConsoleMode = ConsoleMode.OBJECT_GRASP
    follow_enabled: bool = False
    tracking_state: TrackingState = TrackingState.WAITING_HAND
    last_hand_time: float | None = None
    vision_source: VisionSource = VisionSource.MAC_CAMERA

    def switch(self, mode: ConsoleMode) -> None:
        self.mode = mode
        self.pause_follow()

    def switch_source(self, source: VisionSource) -> None:
        self.vision_source = source
        if source == VisionSource.IPHONE_LIDAR:
            self.mode = ConsoleMode.OBJECT_GRASP
        self.pause_follow()

    def enable_follow(self, emergency_stopped: bool) -> bool:
        if self.mode != ConsoleMode.HAND_FOLLOW or emergency_stopped:
            return False
        self.follow_enabled = True
        self.tracking_state = TrackingState.WAITING_HAND
        self.last_hand_time = None
        return True

    def pause_follow(self) -> None:
        self.follow_enabled = False
        self.tracking_state = TrackingState.WAITING_HAND
        self.last_hand_time = None

    def observe_hand(self, detected: bool, now: float, lost_timeout: float) -> TrackingState:
        if not self.follow_enabled:
            self.tracking_state = TrackingState.WAITING_HAND
            return self.tracking_state
        if detected:
            self.last_hand_time = now
            self.tracking_state = TrackingState.TRACKING
        elif self.last_hand_time is None or now - self.last_hand_time > lost_timeout:
            self.tracking_state = TrackingState.PAUSED_LOST
        else:
            self.tracking_state = TrackingState.HOLDING_LAST
        return self.tracking_state

    def can_send_hand(self, now: float, lost_timeout: float) -> bool:
        if self.mode != ConsoleMode.HAND_FOLLOW or not self.follow_enabled:
            return False
        if self.last_hand_time is None or now - self.last_hand_time > lost_timeout:
            return False
        return self.tracking_state in (TrackingState.TRACKING, TrackingState.HOLDING_LAST)
