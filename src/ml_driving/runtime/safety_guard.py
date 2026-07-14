from __future__ import annotations

from dataclasses import dataclass

from ml_driving.models.interfaces import ModelOutput


@dataclass(frozen=True)
class SafetyLimits:
    max_abs_steer: float = 1.0
    min_throttle: float = 0.0
    max_throttle: float = 1.0
    min_brake: float = 0.0
    max_brake: float = 1.0


class SafetyGuard:
    """Clamp model outputs before they can be sent to MORAI control."""

    def __init__(self, limits: SafetyLimits = SafetyLimits()):
        self.limits = limits

    def apply(self, output: ModelOutput) -> ModelOutput:
        return ModelOutput(
            steer=_clamp(output.steer, -self.limits.max_abs_steer, self.limits.max_abs_steer),
            throttle=(
                None
                if output.throttle is None
                else _clamp(output.throttle, self.limits.min_throttle, self.limits.max_throttle)
            ),
            brake=(
                None
                if output.brake is None
                else _clamp(output.brake, self.limits.min_brake, self.limits.max_brake)
            ),
            confidence=output.confidence,
            lane_offset_m=output.lane_offset_m,
        )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

