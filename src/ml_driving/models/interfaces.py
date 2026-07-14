from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ModelInput:
    image: Any
    speed_kmh: float
    previous_steer: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelOutput:
    steer: float
    throttle: Optional[float] = None
    brake: Optional[float] = None
    confidence: Optional[float] = None
    lane_offset_m: Optional[float] = None


class DrivingModel:
    """Base interface implemented by PyTorch, ONNX, or rule-based candidates."""

    name: str
    version: str

    def predict(self, model_input: ModelInput) -> ModelOutput:
        raise NotImplementedError
