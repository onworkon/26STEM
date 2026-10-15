from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image


class Camera(ABC):
    low_quality = False

    @abstractmethod
    def capture_still(self) -> Image.Image: ...

    @abstractmethod
    def preview_jpeg(self) -> bytes: ...

    @abstractmethod
    def status(self) -> dict: ...

    def close(self) -> None:
        pass
