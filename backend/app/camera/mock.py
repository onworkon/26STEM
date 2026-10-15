from __future__ import annotations

import io
import math
import time
from PIL import Image, ImageDraw, ImageFont

from .base import Camera


class MockCamera(Camera):
    def __init__(self) -> None:
        self.number = 0

    def _image(self, number: int, preview: bool = False) -> Image.Image:
        width, height = (800, 480) if preview else (2000, 1200)
        palettes = [((102, 188, 219), (235, 248, 239)), ((237, 176, 153), (255, 240, 202)),
                    ((163, 193, 143), (247, 243, 201)), ((173, 167, 213), (240, 222, 236)),
                    ((242, 185, 123), (240, 243, 209)), ((132, 195, 192), (245, 227, 199))]
        top, bottom = palettes[(number - 1) % len(palettes)]
        image = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(image)
        for y in range(height):
            t = y / height
            color = tuple(int(a * (1 - t) + b * t) for a, b in zip(top, bottom))
            draw.line((0, y, width, y), fill=color)
        scale = width / 800
        # Large shapes and a moving focal point make each saved photo visibly distinct.
        shift = int(math.sin(number * 1.7) * 95 * scale)
        draw.ellipse((int(560*scale)+shift, int(60*scale), int(690*scale)+shift, int(190*scale)), fill="#fff3ca")
        for i in range(5):
            x = int((75 + i * 165 + number * 11) * scale) % width
            y = int((250 + (i % 2) * 28) * scale)
            draw.rounded_rectangle((x, y, x + int(95*scale), y + int(160*scale)), radius=int(25*scale), fill="#375567")
            draw.ellipse((x+int(18*scale), y-int(58*scale), x+int(78*scale), y+int(7*scale)), fill="#ffe3bc")
        draw.rectangle((0, int(405*scale), width, height), fill="#416e75")
        try:
            label_font = ImageFont.truetype("DejaVuSans-Bold.ttf", int(29*scale))
        except OSError:
            label_font = ImageFont.load_default(size=int(29*scale))
        draw.text((int(26*scale), int(24*scale)), f"STEM 4CUT  /  TAKE {number:02d}", fill="#173e55", font=label_font)
        return image

    def capture_still(self) -> Image.Image:
        self.number += 1
        return self._image(self.number)

    def preview_jpeg(self) -> bytes:
        image = self._image(self.number + 1, preview=True)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=80)
        return output.getvalue()

    def status(self) -> dict:
        return {"mode": "mock", "connected": True, "detail": "시뮬레이션 카메라", "low_quality": False}
