"""Small backend-neutral contract for local neural portrait inference."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MotionControl:
    blink: float = 0.0
    smile: float = 0.0
    yaw: float = 0.0
    pitch: float = 0.0
    mouth_open: float = 0.0
    mouth_width: float = 1.0
    lip_roundness: float = 0.0
    mouth_only: bool = False
    gaze_x: float = 0.0
    gaze_y: float = 0.0
    eyebrow: float = 0.0


class NeuralAvatarEngine(ABC):
    @abstractmethod
    def load(self) -> dict[str, Any]:
        """Load exactly one local model set and return actual runtime information."""

    @abstractmethod
    def prepare_avatar(self, image_path: Path, metadata: dict, cache_dir: Path, resolution: int) -> Any:
        """Cache source features, alignment and model-specific data once."""

    @abstractmethod
    def render(self, prepared: Any, control: MotionControl) -> Any:
        """Run actual neural inference and return an RGB frame."""

    @abstractmethod
    def unload(self) -> None:
        """Release model/source resources."""
