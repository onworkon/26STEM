from __future__ import annotations

import asyncio
import hmac
import io
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict

from .config import ROOT, load_config
from .service import FlowError, Studio


class FrameChoice(BaseModel):
    frame_id: str


class Slot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    photo_id: str


class Arrangement(BaseModel):
    slots: list[Slot | None]


class PrintRequest(BaseModel):
    copies: int | None = None


class QuantityChoice(BaseModel):
    copies: int


class DeviceConfig(BaseModel):
    camera: dict | None = None
    remote: dict | None = None
    printer: dict | None = None


def create_app(config: dict | None = None, frames_root: Path | None = None) -> FastAPI:
    settings = config or load_config()
    assets = frames_root or ROOT / "assets" / "frames"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.studio = Studio(settings, assets)
        try:
            yield
        finally:
            app.state.studio.close()

    app = FastAPI(title="STEM 4CUT", lifespan=lifespan)

    def studio(request: Request) -> Studio:
        return request.app.state.studio

    def admin(request: Request, x_admin_pin: str | None = Header(None)) -> None:
        host = request.client.host if request.client else ""
        pin = settings.get("admin_pin", "")
        if host in {"127.0.0.1", "::1", "localhost"} or (pin and x_admin_pin and hmac.compare_digest(pin, x_admin_pin)):
            return
        raise HTTPException(403, "관리자 기능은 PC localhost에서만 사용하거나 PIN이 필요합니다")

    @app.exception_handler(FlowError)
    async def flow_error(_request: Request, error: FlowError):
        return JSONResponse({"detail": error.detail}, status_code=error.code)

    @app.get("/api/health")
    def health():
        return {"ok": True, "name": "STEM 4CUT"}

    @app.get("/api/status")
    def status(s: Studio = Depends(studio)):
        return s.status()

    @app.get("/api/session/active")
    def active(s: Studio = Depends(studio)):
        return s.active()

    @app.get("/api/frames")
    def frames(s: Studio = Depends(studio)):
        return s.catalog.public()

    @app.get("/api/frames/{frame_id}/thumbnail")
    def frame_thumbnail(frame_id: str, s: Studio = Depends(studio)):
        try:
            path = s.catalog.asset(frame_id, "thumbnail")
        except KeyError:
            raise HTTPException(404, "프레임을 찾을 수 없습니다")
        return FileResponse(path, media_type="image/png")

    @app.get("/api/media/{session_id}/{filename}")
    def media(session_id: str, filename: str, s: Studio = Depends(studio)):
        try:
            uuid.UUID(session_id)
        except ValueError:
            raise HTTPException(404)
        session = s.session(session_id)
        allowed = {f"{p['id']}.jpg" for p in session["photos"]} | {"strip.png", "sheet_4x6.png"}
        if filename not in allowed:
            raise HTTPException(404)
        path = s.data / "sessions" / session_id / filename
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/jpeg" if filename.endswith(".jpg") else "image/png", headers={"Cache-Control": "no-store"})

    def error_jpeg(detail: str) -> bytes:
        image = Image.new("RGB", (800, 480), "#d7ecf3")
        draw = ImageDraw.Draw(image)
        draw.text((32, 200), "CAMERA UNAVAILABLE", fill="#163d50")
        draw.text((32, 230), detail[:85], fill="#9a3c3c")
        out = io.BytesIO()
        image.save(out, "JPEG")
        return out.getvalue()

    @app.get("/api/preview.mjpg")
    def preview(s: Studio = Depends(studio)):
        def stream():
            while True:
                camera = s.camera
                try:
                    if hasattr(camera, "mjpeg_frames"):
                        for frame in camera.mjpeg_frames():
                            if s.camera is not camera:
                                break
                            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                    else:
                        frame = camera.preview_jpeg()
                        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                        time.sleep(.3)
                except Exception as exc:
                    frame = error_jpeg(str(exc))
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                    time.sleep(1)
        return StreamingResponse(stream(), media_type="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-store"})

    @app.post("/api/session/{session_id}/capture")
    def capture(session_id: str, s: Studio = Depends(studio)):
        return s.capture(session_id)

    @app.post("/api/session/{session_id}/enter")
    def enter(session_id: str, s: Studio = Depends(studio)):
        return s.enter(session_id)

    @app.post("/api/session/{session_id}/select-quantity")
    def select_quantity(session_id: str, choice: QuantityChoice, s: Studio = Depends(studio)):
        return s.select_quantity(session_id, choice.copies)

    @app.post("/api/session/{session_id}/finish-capture")
    def finish_capture(session_id: str, s: Studio = Depends(studio)):
        return s.finish_capture(session_id)

    @app.post("/api/session/{session_id}/select-frame")
    def select_frame(session_id: str, choice: FrameChoice, s: Studio = Depends(studio)):
        return s.select_frame(session_id, choice.frame_id)

    @app.patch("/api/session/{session_id}/arrangement")
    def arrange(session_id: str, value: Arrangement, s: Studio = Depends(studio)):
        return s.arrange(session_id, [slot.model_dump() if slot else None for slot in value.slots])

    @app.post("/api/session/{session_id}/back-to-arrange")
    def back_to_arrange(session_id: str, s: Studio = Depends(studio)):
        return s.back_to_arrange(session_id)

    @app.post("/api/session/{session_id}/render")
    def render(session_id: str, s: Studio = Depends(studio)):
        return s.render(session_id)

    @app.post("/api/session/{session_id}/print-request")
    def print_request(session_id: str, value: PrintRequest, s: Studio = Depends(studio)):
        return s.print_request(session_id, value.copies)

    @app.get("/api/prints")
    def prints(s: Studio = Depends(studio)):
        # Public status has no filesystem paths or printer configuration secrets.
        return [{k: v for k, v in item.items() if k in {"id", "session_id", "copies", "sheets", "status", "detail", "created_at"}} for item in s.jobs()]

    @app.post("/api/admin/session/start", dependencies=[Depends(admin)])
    def start(s: Studio = Depends(studio)):
        return s.start()

    @app.post("/api/admin/session/reset", dependencies=[Depends(admin)])
    def reset(s: Studio = Depends(studio)):
        s.reset()
        return {"ok": True}

    @app.post("/api/admin/session/{session_id}/return-to-shooting", dependencies=[Depends(admin)])
    def back_to_shooting(session_id: str, s: Studio = Depends(studio)):
        return s.return_to_shooting(session_id)

    @app.post("/api/admin/session/{session_id}/photos", dependencies=[Depends(admin)])
    async def upload_photo(session_id: str, file: UploadFile = File(...), s: Studio = Depends(studio)):
        content = await file.read(20_000_001)
        return s.add_photo(session_id, content)

    @app.get("/api/admin/sessions", dependencies=[Depends(admin)])
    def sessions(s: Studio = Depends(studio)):
        return s.recent_sessions()

    @app.post("/api/admin/sessions/{session_id}/reprint", dependencies=[Depends(admin)])
    def reprint(session_id: str, s: Studio = Depends(studio)):
        return s.reprint(session_id)

    @app.post("/api/admin/prints/{job_id}/retry", dependencies=[Depends(admin)])
    def retry(job_id: str, s: Studio = Depends(studio)):
        return s.retry(job_id)

    @app.post("/api/admin/print-test", dependencies=[Depends(admin)])
    def print_test(s: Studio = Depends(studio)):
        return s.test_page()

    @app.get("/api/admin/prints/{job_id}/pdf", dependencies=[Depends(admin)])
    def download_pdf(job_id: str, s: Studio = Depends(studio)):
        if job_id not in {job["id"] for job in s.jobs()}:
            raise HTTPException(404)
        path = s.data / "prints" / f"{job_id}.pdf"
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="application/pdf", filename=f"stem4cut-{job_id}.pdf")

    @app.get("/api/admin/devices", dependencies=[Depends(admin)])
    def devices(s: Studio = Depends(studio)):
        return s.devices()

    @app.post("/api/admin/devices/configure", dependencies=[Depends(admin)])
    def configure(value: DeviceConfig, s: Studio = Depends(studio)):
        return s.configure_devices(value.model_dump(exclude_none=True))

    @app.get("/api/admin/logs", dependencies=[Depends(admin)])
    def logs(s: Studio = Depends(studio)):
        path = s.data / "app.log"
        return {"lines": path.read_text(encoding="utf-8").splitlines()[-100:]}

    @app.get("/api/admin/paths", dependencies=[Depends(admin)])
    def paths(s: Studio = Depends(studio)):
        return {"sessions": str(s.data / "sessions"), "prints": str(s.data / "prints")}

    @app.post("/api/admin/open-folder/{kind}", dependencies=[Depends(admin)])
    def open_folder(kind: str, s: Studio = Depends(studio)):
        if kind not in {"sessions", "prints"}:
            raise HTTPException(404)
        if os.name != "nt":
            raise HTTPException(501, "폴더 열기는 Windows 운영 PC에서 사용할 수 있습니다")
        os.startfile(str(s.data / kind))
        return {"ok": True}

    @app.post("/api/admin/data/clear", dependencies=[Depends(admin)])
    def clear(s: Studio = Depends(studio)):
        s.clear_data()
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(websocket.app.state.studio.status())
                await asyncio.sleep(1)
        except (WebSocketDisconnect, RuntimeError):
            pass

    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def page(path: str):
        if path not in {"", "tablet", "display", "admin"}:
            raise HTTPException(404)
        index = dist / "index.html"
        if not index.is_file():
            raise HTTPException(503, "프런트엔드 빌드가 필요합니다. frontend에서 npm run build를 실행하세요.")
        return FileResponse(index)

    return app


app = create_app()
