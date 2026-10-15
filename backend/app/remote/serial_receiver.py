from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable


class SerialShutter:
    def __init__(self, on_shutter: Callable[[], None]):
        self.on_shutter = on_shutter
        self.port = ""
        self.baudrate = 115200
        self.last_signal: str | None = None
        self.last_error = ""
        self.connected = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def configure(self, port: str, baudrate: int) -> None:
        self.close()
        self.port, self.baudrate = port, baudrate
        self.last_error = ""
        if port:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="serial-shutter", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        import time
        import serial
        while not self._stop.is_set():
            try:
                with serial.Serial(self.port, self.baudrate, timeout=.5) as device:
                    self.connected, self.last_error = True, ""
                    while not self._stop.is_set():
                        line = device.readline().decode("utf-8", errors="replace").strip()
                        if line == "SHUTTER":
                            self.last_signal = datetime.now(timezone.utc).isoformat()
                            try:
                                self.on_shutter()
                            except Exception as exc:
                                self.last_error = str(exc)
            except Exception as exc:
                self.connected, self.last_error = False, str(exc)
                self._stop.wait(2)
        self.connected = False

    def status(self) -> dict:
        return {"port": self.port, "baudrate": self.baudrate, "connected": self.connected,
                "last_signal": self.last_signal, "detail": self.last_error or ("연결됨" if self.connected else "연결 안 됨")}

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self.connected = False


def serial_ports() -> list[str]:
    try:
        from serial.tools import list_ports
        return [item.device for item in list_ports.comports()]
    except ImportError:
        return []
