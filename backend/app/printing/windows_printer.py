from __future__ import annotations
import os
from pathlib import Path
from PIL import Image, ImageWin
from .base import Printer
from .mock import MockPrinter


def installed_printers() -> list[str]:
    if os.name != "nt":
        return []
    try:
        import win32print
        return [item[2] for item in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]
    except ImportError:
        return []


class WindowsPrinter(Printer):
    def __init__(self, name: str = "") -> None:
        self.name = name

    def status(self) -> dict:
        printers = installed_printers()
        return {"mode": "windows", "connected": os.name == "nt" and bool(printers),
                "detail": "4×6 용지·무테 설정은 Windows 프린터 기본 설정에서 확인하세요.",
                "selected": self.name, "printers": printers}

    def submit(self, sheet: Path, sheet_count: int, output_pdf: Path) -> dict:
        # Save an exact-size fallback PDF even when the spooler fails.
        MockPrinter().submit(sheet, sheet_count, output_pdf)
        if os.name != "nt":
            raise RuntimeError("Windows printing is available only on Windows")
        try:
            import win32print
            import win32ui
            from win32con import HORZRES, VERTRES, PHYSICALWIDTH, PHYSICALHEIGHT, LOGPIXELSX, LOGPIXELSY
        except ImportError as exc:
            raise RuntimeError("Install pywin32 to use the Windows printer adapter") from exc
        name = self.name or win32print.GetDefaultPrinter()
        if name not in installed_printers():
            raise RuntimeError(f"Printer is not installed: {name}")
        dc = win32ui.CreateDC()
        try:
            dc.CreatePrinterDC(name)
            width, height = dc.GetDeviceCaps(HORZRES), dc.GetDeviceCaps(VERTRES)
            physical = (dc.GetDeviceCaps(PHYSICALWIDTH) / dc.GetDeviceCaps(LOGPIXELSX),
                        dc.GetDeviceCaps(PHYSICALHEIGHT) / dc.GetDeviceCaps(LOGPIXELSY))
            if not (3.7 <= physical[0] <= 4.3 and 5.7 <= physical[1] <= 6.3):
                raise RuntimeError(f"Printer default paper is {physical[0]:.1f}×{physical[1]:.1f} inches; set 4×6 portrait first")
            with Image.open(sheet) as original:
                dib = ImageWin.Dib(original.convert("RGB"))
            dc.StartDoc("STEM 4CUT")
            try:
                for _ in range(sheet_count):
                    dc.StartPage()
                    # Keep 2:3 ratio; driver printable margins can reduce final size.
                    scale = min(width / 1200, height / 1800)
                    w, h = round(1200 * scale), round(1800 * scale)
                    x, y = (width - w) // 2, (height - h) // 2
                    dib.draw(dc.GetHandleOutput(), (x, y, x + w, y + h))
                    dc.EndPage()
                dc.EndDoc()
            except Exception:
                dc.AbortDoc()
                raise
        finally:
            dc.DeleteDC()
        return {"status": "spooled", "detail": f"{name} 스풀러에 {sheet_count}장 전송. 실제 배출 여부는 확인되지 않았습니다.", "pdf": str(output_pdf)}
