from __future__ import annotations

import io
import time
import urllib.request
from PIL import Image

from .base import Camera


class HttpCamera(Camera):
    def __init__(self, preview_url: str, snapshot_url: str, method: str = "GET") -> None:
        if not preview_url.startswith(("http://", "https://")) or (snapshot_url and not snapshot_url.startswith(("http://", "https://"))):
            raise ValueError("HTTP camera needs a preview URL and optional snapshot URL")
        if method not in {"GET", "POST"}:
            raise ValueError("Snapshot method must be GET or POST")
        self.preview_url = preview_url
        self.snapshot_url = snapshot_url
        self.method = method
        self.last_error = ""
        self.connected = False
        self.low_quality = not bool(snapshot_url)
        self.last_frame: bytes | None = None
        self.last_frame_at = 0.0

    def capture_still(self) -> Image.Image:
        try:
            if not self.snapshot_url:
                frame = self.last_frame if self.last_frame and time.monotonic() - self.last_frame_at < 5 else next(self.mjpeg_frames())
                image = Image.open(io.BytesIO(frame))
                image.load()
                return image.convert("RGB")
            req = urllib.request.Request(self.snapshot_url, method=self.method)
            with urllib.request.urlopen(req, timeout=8) as response:
                data = response.read(20_000_001)
            if len(data) > 20_000_000:
                raise ValueError("Snapshot exceeds 20 MB")
            image = Image.open(io.BytesIO(data))
            image.load()
            self.connected, self.last_error = True, ""
            return image.convert("RGB")
        except Exception as exc:
            self.connected, self.last_error = False, str(exc)
            raise RuntimeError(f"HTTP snapshot failed: {exc}") from exc

    def preview_jpeg(self) -> bytes:
        # A fresh request per frame is compatible with snapshot-style preview endpoints.
        # MJPEG streams are parsed separately by mjpeg_frames().
        try:
            with urllib.request.urlopen(self.preview_url, timeout=8) as response:
                data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise ValueError("Preview frame exceeds 2 MB")
            image = Image.open(io.BytesIO(data))
            image.load()
            out = io.BytesIO()
            image.convert("RGB").save(out, format="JPEG", quality=80)
            self.connected, self.last_error = True, ""
            return out.getvalue()
        except Exception as exc:
            self.connected, self.last_error = False, str(exc)
            raise RuntimeError(f"HTTP preview failed: {exc}") from exc

    def mjpeg_frames(self):
        try:
            with urllib.request.urlopen(self.preview_url, timeout=10) as response:
                buffer = bytearray()
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        raise RuntimeError("Preview stream ended")
                    buffer.extend(chunk)
                    start = buffer.find(b"\xff\xd8")
                    if start >= 0:
                        end = buffer.find(b"\xff\xd9", start + 2)
                        if end >= 0:
                            frame = bytes(buffer[start:end + 2])
                            del buffer[:end + 2]
                            self.last_frame, self.last_frame_at = frame, time.monotonic()
                            self.connected, self.last_error = True, ""
                            yield frame
                    if len(buffer) > 3_000_000:
                        del buffer[:-2]
        except Exception as exc:
            self.connected, self.last_error = False, str(exc)
            raise

    def status(self) -> dict:
        detail = self.last_error or ("스냅샷 URL 없음: 프리뷰 프레임 저장, 화질 주의" if self.low_quality else "HTTP 카메라 설정됨")
        return {"mode": "http", "connected": self.connected, "detail": detail, "low_quality": self.low_quality}
