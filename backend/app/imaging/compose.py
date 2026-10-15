from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from PIL import Image

STRIP_SIZE = (600, 1800)
SHEET_SIZE = (1200, 1800)


def cover_crop(source: Image.Image, width: int, height: int) -> Image.Image:
    scale = max(width / source.width, height / source.height)
    resized = source.convert("RGB").resize((max(width, round(source.width * scale)), max(height, round(source.height * scale))), Image.Resampling.LANCZOS)
    left = round((resized.width - width) / 2)
    top = round((resized.height - height) / 2)
    return resized.crop((left, top, left + width, top + height))


class FrameCatalog:
    def __init__(self, root: Path):
        self.root = root
        self.lock = RLock()
        self.frames: dict[str, dict] = {}
        self.refresh()
        if len(self.frames) < 2:
            raise RuntimeError("At least two frame designs are required")

    def refresh(self) -> None:
        """Pick up complete frame folders while the server is running."""
        with self.lock:
            found: dict[str, dict] = {}
            for manifest_path in sorted(self.root.glob("*/manifest.json")):
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    slots = manifest["slots"]
                    if not isinstance(manifest.get("name"), str) or not manifest["name"].strip() or not isinstance(slots, list) or len(slots) != 4 or any(
                        s["x"] < 0 or s["y"] < 0 or s["width"] <= 0 or s["height"] <= 0
                        or s["x"] + s["width"] > 600 or s["y"] + s["height"] > 1800 for s in slots
                    ):
                        continue
                    for key, size in (("background", STRIP_SIZE), ("overlay", STRIP_SIZE), ("thumbnail", None)):
                        name = manifest[key]
                        if Path(name).name != name:
                            raise ValueError("Frame asset must be a filename")
                        with Image.open(manifest_path.parent / name) as image:
                            if size and image.size != size:
                                raise ValueError("Invalid frame asset size")
                    thumb = manifest_path.parent / manifest["thumbnail"]
                    found[manifest_path.parent.name] = {
                        "id": manifest_path.parent.name,
                        **manifest,
                        "thumbnail_version": thumb.stat().st_mtime_ns,
                    }
                except (OSError, ValueError, TypeError, KeyError):
                    # A folder being copied is not offered until all files can be read.
                    continue
            self.frames = found

    def public(self) -> list[dict]:
        self.refresh()
        with self.lock:
            return [{"id": f["id"], "name": f["name"], "description": f.get("description", ""), "slots": f["slots"],
                     "thumbnail_url": f"/api/frames/{f['id']}/thumbnail?v={f['thumbnail_version']}"} for f in self.frames.values()]

    def has(self, frame_id: str) -> bool:
        self.refresh()
        with self.lock:
            return frame_id in self.frames

    def frame(self, frame_id: str) -> dict:
        self.refresh()
        with self.lock:
            return self.frames[frame_id]

    def asset(self, frame_id: str, key: str) -> Path:
        frame = self.frame(frame_id)
        return self.root / frame_id / frame[key]


def render_strip(catalog: FrameCatalog, frame_id: str, entries: list[dict], photo_paths: dict[str, Path]) -> Image.Image:
    if len(entries) != 4 or any(not e for e in entries):
        raise ValueError("Four arranged photos are required")
    frame = catalog.frame(frame_id)
    strip = Image.open(catalog.asset(frame_id, "background")).convert("RGBA")
    if strip.size != STRIP_SIZE:
        raise ValueError("Frame background must be 600x1800")
    for slot, entry in zip(frame["slots"], entries):
        with Image.open(photo_paths[entry["photo_id"]]) as original:
            cropped = cover_crop(original, slot["width"], slot["height"])
        strip.alpha_composite(cropped.convert("RGBA"), (slot["x"], slot["y"]))
    with Image.open(catalog.asset(frame_id, "overlay")) as overlay:
        if overlay.size != STRIP_SIZE:
            raise ValueError("Frame overlay must be 600x1800")
        strip.alpha_composite(overlay.convert("RGBA"))
    return strip.convert("RGB")


def make_sheet(strip: Image.Image) -> Image.Image:
    if strip.size != STRIP_SIZE:
        raise ValueError("Strip must be 600x1800")
    sheet = Image.new("RGB", SHEET_SIZE)
    sheet.paste(strip.convert("RGB"), (0, 0))
    sheet.paste(strip.convert("RGB"), (600, 0))
    return sheet


def save_outputs(strip: Image.Image, folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    strip_path, sheet_path = folder / "strip.png", folder / "sheet_4x6.png"
    strip.save(strip_path, format="PNG", dpi=(300, 300))
    make_sheet(strip).save(sheet_path, format="PNG", dpi=(300, 300))
    return strip_path, sheet_path
