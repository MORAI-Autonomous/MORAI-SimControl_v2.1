from __future__ import annotations

from ml_driving.models.interfaces import DrivingModel, ModelInput, ModelOutput
from ml_driving.runtime.safety_guard import SafetyGuard


class InferenceRunner:
    """Small runtime wrapper that always applies safety limits."""

    def __init__(self, model: DrivingModel, safety_guard: SafetyGuard):
        self.model = model
        self.safety_guard = safety_guard

    def predict(self, model_input: ModelInput) -> ModelOutput:
        return self.safety_guard.apply(self.model.predict(model_input))

