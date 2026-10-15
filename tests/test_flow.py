from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import shutil
import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.config import DEFAULTS, ROOT
from backend.app.main import create_app
from backend.app.imaging.compose import cover_crop


def make_app(tmp_path: Path):
    config = copy.deepcopy(DEFAULTS)
    config["data_dir"] = str(tmp_path / "data")
    config["admin_pin"] = "test-only-pin"
    return create_app(config, ROOT / "assets" / "frames")


ADMIN = {"X-Admin-Pin": "test-only-pin"}


def start(client: TestClient):
    response = client.post("/api/admin/session/start", headers=ADMIN)
    assert response.status_code == 200, response.text
    return response.json()


def begin(client: TestClient, session_id: str, copies: int = 2):
    assert client.post(f"/api/session/{session_id}/enter").status_code == 200
    response = client.post(f"/api/session/{session_id}/select-quantity", json={"copies": copies})
    assert response.status_code == 200, response.text
    assert response.json()["stage"] == "SHOOTING"
    assert response.json()["copies"] == copies


def shoot(client: TestClient, app, session_id: str, count: int = 6):
    photos = []
    for _ in range(count):
        app.state.studio.last_capture = 0
        response = client.post(f"/api/session/{session_id}/capture")
        assert response.status_code == 200, response.text
        photos = response.json()["photos"]
    return photos


def arrange_and_render(client: TestClient, session_id: str, photos: list[dict]):
    if len(photos) < 6:
        assert client.post(f"/api/session/{session_id}/finish-capture").status_code == 200
    response = client.post(f"/api/session/{session_id}/select-frame", json={"frame_id": "default-blue"})
    assert response.status_code == 200, response.text
    slots = [{"photo_id": photos[i]["id"]} for i in (3, 1, 0, 2)]
    response = client.patch(f"/api/session/{session_id}/arrangement", json={"slots": slots})
    assert response.status_code == 200, response.text
    response = client.post(f"/api/session/{session_id}/render")
    assert response.status_code == 200, response.text
    return slots


def wait_for_job(client: TestClient, job_id: str):
    for _ in range(60):
        job = next(j for j in client.get("/api/prints").json() if j["id"] == job_id)
        if job["status"] not in {"queued", "sending"}:
            return job
        time.sleep(.1)
    raise AssertionError("Print job did not complete")


def test_new_frame_available_without_restart(tmp_path):
    frames_root = tmp_path / "frames"
    for frame_id in ("default-blue", "default-light"):
        shutil.copytree(ROOT / "assets" / "frames" / frame_id, frames_root / frame_id)
    config = copy.deepcopy(DEFAULTS)
    config["data_dir"] = str(tmp_path / "data")
    config["admin_pin"] = "test-only-pin"
    app = create_app(config, frames_root)

    with TestClient(app) as client:
        assert len(client.get("/api/frames").json()) == 2
        added = frames_root / "festival-new"
        added.mkdir()
        manifest = json.loads((frames_root / "default-light" / "manifest.json").read_text(encoding="utf-8"))
        manifest["name"] = "새 축제 프레임"
        (added / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        assert len(client.get("/api/frames").json()) == 2  # Incomplete copies stay hidden.
        for name in ("background.png", "overlay.png", "thumbnail.png"):
            shutil.copy2(frames_root / "default-light" / name, added / name)

        public = client.get("/api/frames").json()
        assert len(public) == 3
        new_frame = next(frame for frame in public if frame["id"] == "festival-new")
        assert new_frame["name"] == "새 축제 프레임"
        assert client.get(new_frame["thumbnail_url"]).status_code == 200

        session = start(client)
        begin(client, session["id"])
        photos = shoot(client, app, session["id"], 4)
        assert client.post(f"/api/session/{session['id']}/finish-capture").status_code == 200
        chosen = client.post(f"/api/session/{session['id']}/select-frame", json={"frame_id": "festival-new"})
        assert chosen.status_code == 200
        assert chosen.json()["frame_id"] == "festival-new"
        slots = [{"photo_id": photo["id"]} for photo in photos]
        assert client.patch(f"/api/session/{session['id']}/arrangement", json={"slots": slots}).status_code == 200
        assert client.post(f"/api/session/{session['id']}/render").status_code == 200


def test_full_mock_flow_images_idempotency_and_restart(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["ok"]
        assert client.get("/tablet").status_code == 200
        assert client.get("/display").status_code == 200
        assert client.get("/admin").status_code == 200
        assert client.post("/api/admin/session/start").status_code == 403
        session = start(client)
        sid = session["id"]
        assert session["stage"] == "LANDING" and session["copies"] is None
        assert client.post(f"/api/session/{sid}/capture").status_code == 409
        assert client.post(f"/api/session/{sid}/select-quantity", json={"copies": 4}).status_code == 409
        assert client.post(f"/api/session/{sid}/enter").status_code == 200
        assert client.post(f"/api/session/{sid}/select-quantity", json={"copies": 3}).status_code == 422
        chosen = client.post(f"/api/session/{sid}/select-quantity", json={"copies": 4})
        assert chosen.status_code == 200 and chosen.json()["copies"] == 4
        assert client.post(f"/api/session/{sid}/finish-capture").status_code == 409
        first = client.post(f"/api/session/{sid}/capture")
        assert first.status_code == 200
        assert client.post(f"/api/session/{sid}/capture").status_code == 409
        remaining = shoot(client, app, sid, 5)
        photos = client.get("/api/session/active").json()["photos"]
        assert len(photos) == 6
        assert client.get("/api/session/active").json()["stage"] == "CHOOSE_FRAME"
        hashes = [hashlib.sha256(client.get(p["url"]).content).hexdigest() for p in photos]
        assert len(set(hashes)) == 6
        assert client.post(f"/api/session/{sid}/capture").status_code == 409
        slots = arrange_and_render(client, sid, photos)
        folder = tmp_path / "data" / "sessions" / sid
        with Image.open(folder / "strip.png") as strip, Image.open(folder / "sheet_4x6.png") as sheet:
            assert strip.size == (600, 1800)
            assert sheet.size == (1200, 1800)
            assert all(abs(dpi - 300) < .01 for dpi in strip.info["dpi"])
            assert sheet.crop((0, 0, 600, 1800)).tobytes() == sheet.crop((600, 0, 1200, 1800)).tobytes()
            assert strip.tobytes() == sheet.crop((0, 0, 600, 1800)).tobytes()
            # Compare a photo pixel away from the frame overlay with the crop service.
            with Image.open(folder / f"{slots[0]['photo_id']}.jpg") as original:
                expected = cover_crop(original, 532, 319)
            assert strip.getpixel((34 + 260, 245 + 160)) == expected.getpixel((260, 160))
        assert client.get(f"/api/session/{sid}/slot-preview").status_code == 404
        assert client.patch(f"/api/session/{sid}/arrangement", json={"slots": [
            {"photo_id": photos[0]["id"], "zoom": 1.2}, None, None, None]}).status_code == 422
        assert client.post(f"/api/session/{sid}/print-request", json={"copies": 6}).status_code == 422
        response = client.post(f"/api/session/{sid}/print-request", json={})
        assert response.status_code == 200, response.text
        job_id = response.json()["id"]
        duplicate = client.post(f"/api/session/{sid}/print-request", json={"copies": 6})
        assert duplicate.json()["id"] == job_id
        assert len([j for j in client.get("/api/prints").json() if j["session_id"] == sid]) == 1
        assert wait_for_job(client, job_id)["status"] == "file_saved"
        pdf = (tmp_path / "data" / "prints" / f"{job_id}.pdf").read_bytes()
        assert len(re.findall(rb"/Type\s*/Page\b", pdf)) == 2
        assert client.get("/api/session/active").json()["stage"] == "DONE"
        reprint = client.post(f"/api/admin/sessions/{sid}/reprint", headers=ADMIN)
        assert reprint.status_code == 200 and reprint.json()["id"] != job_id
        assert wait_for_job(client, reprint.json()["id"])["status"] == "file_saved"
        next_session = start(client)
        assert next_session["id"] != sid
        assert client.post("/api/admin/session/reset", headers=ADMIN).status_code == 200
    with TestClient(make_app(tmp_path)) as client:
        assert client.get("/api/session/active").json() is None
        assert client.get("/api/admin/sessions", headers=ADMIN).json()[0]["id"] == next_session["id"]
        assert len(client.get("/api/prints").json()) == 2
        assert client.get(f"/api/media/{sid}/strip.png").status_code == 200


def test_quantity_mapping_and_failure_recovery(tmp_path):
    with TestClient(make_app(tmp_path)) as client:
        for copies in (2, 4, 6):
            session = start(client)
            sid = session["id"]
            begin(client, sid, copies)
            photos = shoot(client, client.app, sid, 4)
            arrange_and_render(client, sid, photos)
            job = client.post(f"/api/session/{sid}/print-request", json={}).json()
            assert job["sheets"] == copies // 2
            assert wait_for_job(client, job["id"])["status"] == "file_saved"
            pdf = (tmp_path / "data" / "prints" / f"{job['id']}.pdf").read_bytes()
            assert len(re.findall(rb"/Type\s*/Page\b", pdf)) == copies // 2
        new = start(client)
        sid = new["id"]
        begin(client, sid)
        changed = client.post("/api/admin/devices/configure", headers=ADMIN,
                              json={"camera": {"mode": "http", "preview_mjpeg_url": "http://127.0.0.1:1/stream",
                                                "snapshot_jpeg_url": "http://127.0.0.1:1/still", "snapshot_method": "GET"}})
        assert changed.status_code == 200
        failure = client.post(f"/api/session/{sid}/capture")
        assert failure.status_code == 503 and "카메라" in failure.json()["detail"]
        assert client.get("/api/session/active").json()["photos"] == []
        image = Image.new("RGB", (1500, 900), "#d8e8ed")
        out = io.BytesIO(); image.save(out, "JPEG")
        uploaded = client.post(f"/api/admin/session/{sid}/photos", headers=ADMIN,
                               files={"file": ("fallback.jpg", out.getvalue(), "image/jpeg")})
        assert uploaded.status_code == 200 and len(uploaded.json()["photos"]) == 1
        assert client.get("/api/session/active").json()["stage"] == "SHOOTING"
        assert client.post("/api/admin/session/reset", headers=ADMIN).status_code == 200
        assert client.post("/api/admin/data/clear", headers=ADMIN).status_code == 200
        assert client.get("/api/admin/sessions", headers=ADMIN).json() == []


def test_active_session_recovers_after_restart(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        sid = start(client)["id"]
        begin(client, sid, 6)
        app.state.studio._serial_capture()
        app.state.studio._serial_capture()
        assert len(client.get("/api/session/active").json()["photos"]) == 1
        photos = shoot(client, app, sid, 3)
        assert client.post(f"/api/session/{sid}/finish-capture").status_code == 200
        assert client.post(f"/api/session/{sid}/select-frame", json={"frame_id": "default-light"}).status_code == 200
        entries = [{"photo_id": photo["id"]} for photo in photos]
        assert client.patch(f"/api/session/{sid}/arrangement", json={"slots": [entries[0], None, None, None]}).status_code == 200
        assert client.patch(f"/api/session/{sid}/arrangement", json={"slots": [entries[0]] * 4}).status_code == 422
    with TestClient(make_app(tmp_path)) as client:
        restored = client.get("/api/session/active").json()
        assert restored["id"] == sid and restored["stage"] == "ARRANGE"
        assert restored["photos"] == photos
        assert restored["arrangement"][0] == entries[0]
        assert client.patch(f"/api/session/{sid}/arrangement", json={"slots": entries}).status_code == 200
        assert client.post(f"/api/session/{sid}/render").status_code == 200


def test_failed_printer_job_can_retry_without_blocking_next_team(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        sid = start(client)["id"]
        begin(client, sid)
        photos = shoot(client, app, sid, 4)
        arrange_and_render(client, sid, photos)
        assert client.post("/api/admin/devices/configure", headers=ADMIN, json={"printer": {"mode": "windows"}}).status_code == 200
        job = client.post(f"/api/session/{sid}/print-request", json={}).json()
        assert wait_for_job(client, job["id"])["status"] == "error"
        next_team = start(client)
        assert next_team["stage"] == "LANDING"
        assert client.post("/api/admin/devices/configure", headers=ADMIN, json={"printer": {"mode": "mock"}}).status_code == 200
        assert client.post(f"/api/admin/prints/{job['id']}/retry", headers=ADMIN).status_code == 200
        assert wait_for_job(client, job["id"])["status"] == "file_saved"
        assert client.get("/api/session/active").json()["id"] == next_team["id"]


def test_legacy_session_keeps_photo_order_and_drops_edit_values(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    with sqlite3.connect(data / "studio.sqlite3") as db:
        db.execute("""CREATE TABLE sessions (
            id TEXT PRIMARY KEY, stage TEXT NOT NULL, active INTEGER NOT NULL,
            frame_id TEXT, photos TEXT NOT NULL, arrangement TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)", (
            "legacy-session", "ARRANGE", 1, "default-light", "[]",
            json.dumps([{"photo_id": "first", "focus_x": .1, "focus_y": .9, "zoom": 1.8}, None, None, None]),
            "2026-01-01", "2026-01-01"))
    with TestClient(make_app(tmp_path)) as client:
        restored = client.get("/api/session/active").json()
        assert restored["id"] == "legacy-session"
        assert restored["copies"] == 2
        assert restored["arrangement"] == [{"photo_id": "first"}, None, None, None]
