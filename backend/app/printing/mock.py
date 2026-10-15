from __future__ import annotations
from pathlib import Path
from PIL import Image
from .base import Printer


class MockPrinter(Printer):
    def submit(self, sheet: Path, sheet_count: int, output_pdf: Path) -> dict:
        with Image.open(sheet) as original:
            image = original.convert("RGB")
            image.save(output_pdf, "PDF", resolution=300, save_all=True, append_images=[image.copy() for _ in range(sheet_count - 1)])
        return {"status": "file_saved", "detail": "파일 저장 완료. 실제 인쇄는 수행하지 않았습니다.", "pdf": str(output_pdf)}

    def status(self) -> dict:
        return {"mode": "mock", "connected": True, "detail": "PNG/PDF 파일 전용 모드"}
