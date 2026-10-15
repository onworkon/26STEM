from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path


class Printer(ABC):
    @abstractmethod
    def submit(self, sheet: Path, sheet_count: int, output_pdf: Path) -> dict: ...

    @abstractmethod
    def status(self) -> dict: ...
