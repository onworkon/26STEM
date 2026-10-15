from __future__ import annotations

import io
from PIL import Image
from .base import Camera


class UsbCamera(Camera):
    low_quality = False

    def __init__(self, index: int) -> None:
        self.index = index
        self.last_error = ""
        self.connected = False

    def _frame(self) -> Image.Image:
        try:
            import cv2
            cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW if __import__("os").name == "nt" else cv2.CAP_ANY)
            try:
                if not cap.isOpened():
                    raise RuntimeError(f"USB camera {self.index} is unavailable")
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError("USB camera returned no frame")
                self.last_error = ""
                self.connected = True
                return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            finally:
                cap.release()
        except ImportError as exc:
            self.last_error = "opencv-python is required for USB camera mode"
            self.connected = False
            raise RuntimeError(self.last_error) from exc
        except Exception as exc:
            self.last_error = str(exc)
            self.connected = False
            raise

    def capture_still(self) -> Image.Image:
        return self._frame()

    def preview_jpeg(self) -> bytes:
        out = io.BytesIO()
        image = self._frame()
        image.thumbnail((800, 480))
        image.save(out, format="JPEG", quality=80)
        return out.getvalue()

    def status(self) -> dict:
        return {"mode": "usb", "connected": self.connected, "detail": self.last_error or f"USB 카메라 {self.index} (인쇄 해상도 확인 필요)", "low_quality": False}
