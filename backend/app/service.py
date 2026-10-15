from __future__ import annotations

import io
import json
import logging
import shutil
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps
from PIL import ImageDraw

from .camera.mock import MockCamera
from .camera.http_camera import HttpCamera
from .camera.usb_camera import UsbCamera
from .imaging.compose import FrameCatalog, render_strip, save_outputs
from .printing.mock import MockPrinter
from .printing.windows_printer import WindowsPrinter, installed_printers
from .remote.serial_receiver import SerialShutter, serial_ports


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FlowError(Exception):
    def __init__(self, detail: str, code: int = 409):
        super().__init__(detail)
        self.detail, self.code = detail, code


class Studio:
    def __init__(self, config: dict, frames_root: Path):
        self.config = config
        self.data = Path(config["data_dir"])
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "sessions").mkdir(exist_ok=True)
        (self.data / "prints").mkdir(exist_ok=True)
        self.logger = logging.getLogger(f"stem4cut.{id(self)}")
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler(self.data / "app.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.addHandler(handler)
        self.db = sqlite3.connect(self.data / "studio.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, stage TEXT NOT NULL, active INTEGER NOT NULL,
                frame_id TEXT, photos TEXT NOT NULL, arrangement TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, copies INTEGER
            );
            CREATE TABLE IF NOT EXISTS print_jobs (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, kind TEXT NOT NULL,
                copies INTEGER NOT NULL, sheets INTEGER NOT NULL,
                status TEXT NOT NULL, detail TEXT NOT NULL, printer_mode TEXT NOT NULL,
                printer_name TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_initial_print ON print_jobs(session_id) WHERE kind = 'initial';
        """)
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(sessions)")}
        if "copies" not in columns:
            self.db.execute("ALTER TABLE sessions ADD COLUMN copies INTEGER")
        self.db.execute("""UPDATE sessions SET copies=(SELECT copies FROM print_jobs
                          WHERE session_id=sessions.id AND kind='initial' LIMIT 1)
                          WHERE copies IS NULL AND EXISTS (SELECT 1 FROM print_jobs
                          WHERE session_id=sessions.id AND kind='initial')""")
        self.db.execute("UPDATE sessions SET copies=2 WHERE copies IS NULL AND stage NOT IN ('LANDING','QUANTITY')")
        for row in list(self.db.execute("SELECT id, arrangement FROM sessions")):
            entries = json.loads(row["arrangement"])
            selected = [{"photo_id": entry["photo_id"]} if entry else None for entry in entries]
            if selected != entries:
                self.db.execute("UPDATE sessions SET arrangement=? WHERE id=?", (json.dumps(selected), row["id"]))
        self.db.execute("UPDATE print_jobs SET status='uncertain', detail='재시작 전 스풀 전송 중단 여부 불명. 운영자가 확인 후 재시도하세요.' WHERE status='sending'")
        self.db.commit()
        self.lock = threading.RLock()
        self.capture_busy = False
        self.last_capture = 0.0
        self.catalog = FrameCatalog(frames_root)
        settings_file = self.data / "devices.json"
        if settings_file.exists():
            saved = json.loads(settings_file.read_text(encoding="utf-8"))
            for section in ("camera", "remote", "printer"):
                if isinstance(saved.get(section), dict):
                    self.config[section].update({k: v for k, v in saved[section].items() if k in self.config[section]})
        self.camera = self._camera(self.config["camera"])
        self.printer = self._printer(self.config["printer"])
        self.remote = SerialShutter(self._serial_capture)
        remote = self.config["remote"]
        self.remote.configure(remote["port"], int(remote["baudrate"]))
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._print_loop, name="print-worker", daemon=True)
        self._worker.start()
        self.on_change = lambda: None

    def close(self):
        self._stop.set()
        self._worker.join(timeout=3)
        self.remote.close()
        self.camera.close()
        self.db.close()
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)

    def _camera(self, options: dict):
        mode = options["mode"]
        if mode == "mock":
            return MockCamera()
        if mode == "http":
            return HttpCamera(options["preview_mjpeg_url"], options["snapshot_jpeg_url"], options["snapshot_method"])
        if mode == "usb":
            return UsbCamera(int(options["usb_index"]))
        raise FlowError("지원하지 않는 카메라 모드", 422)

    def _printer(self, options: dict):
        if options["mode"] == "mock":
            return MockPrinter()
        if options["mode"] == "windows":
            return WindowsPrinter(options.get("name", ""))
        raise FlowError("지원하지 않는 프린터 모드", 422)

    def _row(self, row) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        if "photos" in result:
            result["photos"] = json.loads(result["photos"])
            result["arrangement"] = json.loads(result["arrangement"])
        return result

    def _session(self, session_id: str) -> dict:
        row = self._row(self.db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())
        if not row:
            raise FlowError("세션을 찾을 수 없습니다", 404)
        return row

    def session(self, session_id: str) -> dict:
        with self.lock:
            return self._session(session_id)

    def active(self) -> dict | None:
        with self.lock:
            return self._row(self.db.execute("SELECT * FROM sessions WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone())

    def status(self) -> dict:
        with self.lock:
            active = self.active()
            return {"active_id": active["id"] if active else None, "stage": active["stage"] if active else "IDLE",
                    "photo_count": len(active["photos"]) if active else 0,
                    "camera": self.camera.status(), "printer": self.printer.status(), "remote": self.remote.status(),
                    "print_counts": {row["status"]: row["n"] for row in self.db.execute("SELECT status, COUNT(*) n FROM print_jobs GROUP BY status")}}

    def _save(self, session: dict):
        session["updated_at"] = now()
        self.db.execute("UPDATE sessions SET stage=?, active=?, frame_id=?, photos=?, arrangement=?, copies=?, updated_at=? WHERE id=?",
                        (session["stage"], session["active"], session["frame_id"], json.dumps(session["photos"]),
                         json.dumps(session["arrangement"]), session["copies"], session["updated_at"], session["id"]))
        self.db.commit()
        self.on_change()

    def start(self) -> dict:
        with self.lock:
            current = self.active()
            if current and current["stage"] not in {"PRINT_REQUESTED", "DONE"}:
                raise FlowError("진행 중인 세션을 먼저 종료하세요")
            self.db.execute("UPDATE sessions SET active=0 WHERE active=1")
            session_id = str(uuid.uuid4())
            timestamp = now()
            self.db.execute("INSERT INTO sessions (id,stage,active,frame_id,photos,arrangement,created_at,updated_at,copies) VALUES (?,?,?,?,?,?,?,?,?)",
                            (session_id, "LANDING", 1, None, "[]", "[null,null,null,null]", timestamp, timestamp, None))
            self.db.commit()
            (self.data / "sessions" / session_id).mkdir()
            self.last_capture = 0.0
            self.logger.info("session started %s", session_id)
            self.on_change()
            return self._session(session_id)

    def enter(self, session_id: str) -> dict:
        with self.lock:
            session = self._session(session_id)
            if not session["active"] or session["stage"] != "LANDING":
                raise FlowError("시작 화면이 아닙니다")
            session["stage"] = "QUANTITY"
            self._save(session)
            return session

    def select_quantity(self, session_id: str, copies: int) -> dict:
        with self.lock:
            session = self._session(session_id)
            if copies not in (2, 4, 6):
                raise FlowError("스트립 수는 2, 4, 6 중 하나여야 합니다", 422)
            if not session["active"] or session["stage"] != "QUANTITY":
                raise FlowError("장수 선택 단계가 아닙니다")
            session["copies"] = copies
            session["stage"] = "SHOOTING"
            self._save(session)
            return session

    def reset(self) -> None:
        with self.lock:
            current = self.active()
            if current:
                current["active"] = 0
                current["stage"] = "DONE"
                self._save(current)
                self.logger.info("session closed %s", current["id"])

    def return_to_shooting(self, session_id: str) -> dict:
        with self.lock:
            session = self._session(session_id)
            if not session["active"] or session["stage"] not in {"CHOOSE_FRAME", "ARRANGE", "REVIEW"}:
                raise FlowError("이 단계에서는 촬영으로 돌아갈 수 없습니다")
            session["stage"] = "SHOOTING"
            self._save(session)
            return session

    def capture(self, session_id: str) -> dict:
        with self.lock:
            session = self._session(session_id)
            if not session["active"] or session["stage"] != "SHOOTING":
                raise FlowError("촬영 단계가 아닙니다")
            if len(session["photos"]) >= 6:
                raise FlowError("최대 6장까지 촬영할 수 있습니다")
            if self.capture_busy or time.monotonic() - self.last_capture < .65:
                raise FlowError("연속 촬영 신호가 무시되었습니다")
            self.capture_busy = True
            self.last_capture = time.monotonic()
        try:
            delay = float(self.config.get("capture_delay_seconds", 0))
            if delay > 0:
                time.sleep(min(delay, 10))
            image = self.camera.capture_still()
            image = ImageOps.exif_transpose(image).convert("RGB")
            if image.width < 320 or image.height < 200:
                raise RuntimeError("캡처 이미지 해상도가 너무 낮습니다")
            photo_id = str(uuid.uuid4())
            folder = self.data / "sessions" / session_id
            folder.mkdir(exist_ok=True)
            temp = folder / f"{photo_id}.tmp"
            dest = folder / f"{photo_id}.jpg"
            image.save(temp, format="JPEG", quality=94)
            temp.replace(dest)
            with self.lock:
                session = self._session(session_id)
                if not session["active"] or session["stage"] != "SHOOTING":
                    dest.unlink(missing_ok=True)
                    raise FlowError("촬영 단계가 종료되었습니다")
                photo = {"id": photo_id, "url": f"/api/media/{session_id}/{photo_id}.jpg", "width": image.width, "height": image.height,
                         "low_quality": image.width < 1200 or image.height < 720 or self.camera.low_quality}
                session["photos"].append(photo)
                if len(session["photos"]) == 6:
                    session["stage"] = "CHOOSE_FRAME"
                self._save(session)
                self.logger.info("captured %s %s", session_id, photo_id)
                return session
        except Exception as exc:
            self.logger.error("capture failed: %s", exc)
            if isinstance(exc, FlowError):
                raise
            raise FlowError(f"카메라 촬영 실패: {exc}", 503) from exc
        finally:
            with self.lock:
                self.capture_busy = False

    def _serial_capture(self):
        session = self.active()
        if session and session["stage"] == "SHOOTING":
            try:
                self.capture(session["id"])
            except Exception as exc:
                self.logger.warning("serial capture ignored: %s", exc)

    def add_photo(self, session_id: str, content: bytes) -> dict:
        if len(content) > 20_000_000:
            raise FlowError("파일은 20MB 이하이어야 합니다", 413)
        try:
            with Image.open(io.BytesIO(content)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
            if image.width < 320 or image.height < 200:
                raise ValueError("Image resolution too low")
        except Exception as exc:
            raise FlowError(f"이미지를 열 수 없습니다: {exc}", 422) from exc
        with self.lock:
            session = self._session(session_id)
            if not session["active"] or session["stage"] != "SHOOTING" or len(session["photos"]) >= 6:
                raise FlowError("현재 세션의 촬영 단계에만 사진을 추가할 수 있습니다")
            photo_id = str(uuid.uuid4())
            folder = self.data / "sessions" / session_id
            folder.mkdir(exist_ok=True)
            image.save(folder / f"{photo_id}.jpg", format="JPEG", quality=94)
            session["photos"].append({"id": photo_id, "url": f"/api/media/{session_id}/{photo_id}.jpg", "width": image.width,
                                      "height": image.height, "low_quality": image.width < 1200 or image.height < 720})
            if len(session["photos"]) == 6:
                session["stage"] = "CHOOSE_FRAME"
            self._save(session)
            self.logger.info("manual photo added %s", session_id)
            return session

    def finish_capture(self, session_id: str) -> dict:
        with self.lock:
            session = self._session(session_id)
            if session["stage"] == "CHOOSE_FRAME":
                return session
            if not session["active"] or session["stage"] != "SHOOTING" or len(session["photos"]) < 4:
                raise FlowError("촬영 단계에서 사진 4장 이상이 필요합니다")
            session["stage"] = "CHOOSE_FRAME"
            self._save(session)
            return session

    def select_frame(self, session_id: str, frame_id: str) -> dict:
        with self.lock:
            session = self._session(session_id)
            if not session["active"] or session["stage"] not in {"CHOOSE_FRAME", "ARRANGE"}:
                raise FlowError("프레임 선택 단계가 아닙니다")
            if not self.catalog.has(frame_id):
                raise FlowError("프레임을 찾을 수 없습니다", 404)
            session["frame_id"] = frame_id
            session["stage"] = "ARRANGE"
            self._save(session)
            return session

    def arrange(self, session_id: str, entries: list[dict | None]) -> dict:
        if len(entries) != 4:
            raise FlowError("슬롯은 정확히 4개여야 합니다", 422)
        with self.lock:
            session = self._session(session_id)
            if not session["active"] or session["stage"] not in {"ARRANGE", "REVIEW"}:
                raise FlowError("사진 배치 단계가 아닙니다")
            valid = {p["id"] for p in session["photos"]}
            used = set()
            normalized = []
            for entry in entries:
                if entry is None:
                    normalized.append(None)
                    continue
                if set(entry) != {"photo_id"}:
                    raise FlowError("사진 가공 값은 지정할 수 없습니다", 422)
                photo_id = entry.get("photo_id")
                if photo_id not in valid or photo_id in used:
                    raise FlowError("사진은 서로 다른 4장을 사용해야 합니다", 422)
                used.add(photo_id)
                normalized.append({"photo_id": photo_id})
            session["arrangement"] = normalized
            session["stage"] = "ARRANGE"
            self._save(session)
            return session

    def back_to_arrange(self, session_id: str) -> dict:
        with self.lock:
            session = self._session(session_id)
            if session["stage"] != "REVIEW":
                raise FlowError("결과 확인 단계가 아닙니다")
            session["stage"] = "ARRANGE"
            self._save(session)
            return session

    def _photo_paths(self, session: dict) -> dict[str, Path]:
        folder = self.data / "sessions" / session["id"]
        return {p["id"]: folder / f"{p['id']}.jpg" for p in session["photos"]}

    def render(self, session_id: str) -> dict:
        with self.lock:
            session = self._session(session_id)
            if not session["active"] or session["stage"] not in {"ARRANGE", "REVIEW"}:
                raise FlowError("사진 배치 후 결과를 만들 수 있습니다")
            if not session["frame_id"] or any(e is None for e in session["arrangement"]):
                raise FlowError("서로 다른 사진 4장을 모두 배치하세요")
            strip = render_strip(self.catalog, session["frame_id"], session["arrangement"], self._photo_paths(session))
            save_outputs(strip, self.data / "sessions" / session_id)
            session["stage"] = "REVIEW"
            self._save(session)
            return session

    def _job(self, row) -> dict:
        return dict(row)

    def jobs(self) -> list[dict]:
        with self.lock:
            return [self._job(row) for row in self.db.execute("SELECT * FROM print_jobs ORDER BY created_at DESC LIMIT 100")]

    def print_request(self, session_id: str, copies: int | None = None) -> dict:
        with self.lock:
            session = self._session(session_id)
            existing = self.db.execute("SELECT * FROM print_jobs WHERE session_id=? AND kind='initial'", (session_id,)).fetchone()
            if existing:
                return self._job(existing)
            selected_copies = session["copies"]
            if selected_copies not in (2, 4, 6):
                raise FlowError("촬영 전에 인쇄 장수를 선택하세요")
            if copies is not None and copies != selected_copies:
                raise FlowError("시작할 때 선택한 장수와 다릅니다", 422)
            if not session["active"] or session["stage"] != "REVIEW":
                raise FlowError("최종 결과 확인 후 인쇄할 수 있습니다")
            if not (self.data / "sessions" / session_id / "sheet_4x6.png").exists():
                raise FlowError("인쇄 파일이 없습니다. 결과를 다시 만드세요")
            job_id = str(uuid.uuid4())
            timestamp = now()
            self.db.execute("INSERT INTO print_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (job_id, session_id, "initial", selected_copies, selected_copies // 2, "queued", "인쇄 대기", self.config["printer"]["mode"],
                             self.config["printer"].get("name", ""), timestamp, timestamp))
            session["stage"] = "PRINT_REQUESTED"
            self._save(session)
            self.logger.info("print requested %s %s sheets=%d", session_id, job_id, selected_copies // 2)
            return self._job(self.db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())

    def reprint(self, session_id: str) -> dict:
        with self.lock:
            session = self._session(session_id)
            prior = self.db.execute("SELECT * FROM print_jobs WHERE session_id=? AND kind='initial'", (session_id,)).fetchone()
            if not prior:
                raise FlowError("처음 인쇄 요청이 없는 세션입니다")
            if not (self.data / "sessions" / session_id / "sheet_4x6.png").exists():
                raise FlowError("인쇄 파일이 삭제되었습니다")
            job_id = str(uuid.uuid4())
            timestamp = now()
            self.db.execute("INSERT INTO print_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (job_id, session_id, "reprint", prior["copies"], prior["sheets"], "queued", "직원 재인쇄 대기",
                             self.config["printer"]["mode"], self.config["printer"].get("name", ""), timestamp, timestamp))
            self.db.commit()
            self.on_change()
            self.logger.info("reprint requested %s %s", session_id, job_id)
            return self._job(self.db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())

    def retry(self, job_id: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise FlowError("인쇄 작업을 찾을 수 없습니다", 404)
            if row["status"] not in {"error", "uncertain"}:
                raise FlowError("오류 또는 상태 불명 작업만 재시도할 수 있습니다")
            self.db.execute("UPDATE print_jobs SET status='queued', detail='직원 재시도 대기', printer_mode=?, printer_name=?, updated_at=? WHERE id=?",
                            (self.config["printer"]["mode"], self.config["printer"].get("name", ""), now(), job_id))
            self.db.commit()
            self.on_change()
            return self._job(self.db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())

    def _print_loop(self):
        while not self._stop.wait(.2):
            with self.lock:
                row = self.db.execute("SELECT * FROM print_jobs WHERE status='queued' ORDER BY created_at, rowid LIMIT 1").fetchone()
                if not row:
                    continue
                job = dict(row)
                self.db.execute("UPDATE print_jobs SET status='sending', detail='파일 생성 및 스풀 전송 중', updated_at=? WHERE id=?", (now(), job["id"]))
                self.db.commit()
                self.on_change()
            try:
                sheet = (self.data / "prints" / "test_sheet_4x6.png") if job["kind"] == "test" else (self.data / "sessions" / job["session_id"] / "sheet_4x6.png")
                pdf = self.data / "prints" / f"{job['id']}.pdf"
                printer = MockPrinter() if job["printer_mode"] == "mock" else WindowsPrinter(job["printer_name"])
                outcome = printer.submit(sheet, job["sheets"], pdf)
                status, detail = outcome["status"], outcome["detail"]
            except Exception as exc:
                status, detail = "error", str(exc)
                self.logger.error("print failed %s: %s", job["id"], exc)
            with self.lock:
                self.db.execute("UPDATE print_jobs SET status=?, detail=?, updated_at=? WHERE id=?", (status, detail, now(), job["id"]))
                if job["kind"] != "test":
                    session = self._session(job["session_id"])
                    if session["stage"] == "PRINT_REQUESTED":
                        session["stage"] = "DONE"
                        self._save(session)
                    else:
                        self.db.commit()
                else:
                    self.db.commit()
                self.on_change()

    def test_page(self) -> dict:
        with self.lock:
            sheet = Image.new("RGB", (1200, 1800), "white")
            draw = ImageDraw.Draw(sheet)
            draw.rectangle((10, 10, 1189, 1789), outline="#222222", width=5)
            draw.line((600, 0, 600, 1800), fill="#222222", width=3)
            for x in (0, 600):
                draw.text((x + 80, 130), "STEM 4CUT / 4x6 TEST", fill="#222222")
                draw.rectangle((x + 60, 250, x + 540, 1500), outline="#777777", width=8)
            sheet.save(self.data / "prints" / "test_sheet_4x6.png", dpi=(300, 300))
            job_id, timestamp = str(uuid.uuid4()), now()
            self.db.execute("INSERT INTO print_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (job_id, "__test__", "test", 2, 1, "queued", "테스트 페이지 대기", self.config["printer"]["mode"],
                             self.config["printer"].get("name", ""), timestamp, timestamp))
            self.db.commit()
            self.on_change()
            return self._job(self.db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())

    def devices(self) -> dict:
        return {"camera": {**self.config["camera"], **self.camera.status()}, "printer": {**self.config["printer"], **self.printer.status()},
                "remote": {**self.config["remote"], **self.remote.status()}, "printers": installed_printers(), "serial_ports": serial_ports()}

    def configure_devices(self, changes: dict) -> dict:
        with self.lock:
            if self.capture_busy:
                raise FlowError("촬영 중에는 장비를 변경할 수 없습니다")
            new = {section: dict(self.config[section]) for section in ("camera", "remote", "printer")}
            for section, updates in changes.items():
                if section not in new or not isinstance(updates, dict) or set(updates) - set(new[section]):
                    raise FlowError("장비 설정 항목이 올바르지 않습니다", 422)
                new[section].update(updates)
            try:
                camera = self._camera(new["camera"])
                printer = self._printer(new["printer"])
                baud = int(new["remote"]["baudrate"])
                if not (1200 <= baud <= 2000000):
                    raise ValueError("Invalid baudrate")
            except (ValueError, TypeError) as exc:
                raise FlowError(str(exc), 422) from exc
            self.camera.close()
            self.camera, self.printer = camera, printer
            self.remote.configure(new["remote"]["port"], baud)
            for section in new:
                self.config[section] = new[section]
            (self.data / "devices.json").write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
            self.on_change()
            return self.devices()

    def recent_sessions(self) -> list[dict]:
        with self.lock:
            return [self._row(row) for row in self.db.execute("SELECT * FROM sessions ORDER BY created_at DESC LIMIT 10")]

    def clear_data(self) -> None:
        with self.lock:
            if self.active() or self.db.execute("SELECT 1 FROM print_jobs WHERE status IN ('queued','sending') LIMIT 1").fetchone():
                raise FlowError("활성 세션과 인쇄 대기열을 먼저 종료하세요")
            self.db.execute("DELETE FROM print_jobs")
            self.db.execute("DELETE FROM sessions")
            self.db.commit()
            for name in ("sessions", "prints"):
                folder = self.data / name
                shutil.rmtree(folder)
                folder.mkdir()
            self.logger.info("local session and print files deleted")
            self.on_change()
