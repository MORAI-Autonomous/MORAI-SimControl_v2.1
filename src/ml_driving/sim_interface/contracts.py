from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class VehicleSnapshot:
    timestamp_s: float
    entity_id: str
    speed_kmh: float
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    yaw_deg: Optional[float] = None


@dataclass(frozen=True)
class ControlCommand:
    steer: float
    throttle: float
    brake: float


class SimulatorAdapter:
    """Minimal simulator IO contract for future adapters."""

    def latest_camera_frame(self) -> Any:
        raise NotImplementedError

    def latest_vehicle_snapshot(self) -> VehicleSnapshot:
        raise NotImplementedError

    def send_control(self, entity_id: str, command: ControlCommand) -> None:
        raise NotImplementedError
