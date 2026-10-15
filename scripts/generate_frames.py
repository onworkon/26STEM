"""Generate missing 300 dpi frame assets, or regenerate with --force."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1] / "assets" / "frames"


def font(size: int, bold: bool = False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default(size=size)


def generate(frame_id: str, bg: str, ink: str, accent: str):
    folder = ROOT / frame_id
    if "--force" not in sys.argv and all((folder / name).exists() for name in ("background.png", "overlay.png", "thumbnail.png")):
        return
    background = Image.new("RGB", (600, 1800), bg)
    canvas = ImageDraw.Draw(background)
    # Leave every photo position empty until a captured photo is composited.
    for y in (245, 585, 925, 1265):
        canvas.rectangle((34, y, 566, y+319), fill="#ffffff")
    background.save(folder / "background.png", dpi=(300, 300))

    overlay = Image.new("RGBA", (600, 1800), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.text((34, 54), "STEM 4CUT", fill=ink, font=font(60, True))
    draw.text((36, 143), "MAKER PHOTO", fill=accent, font=font(20, True))
    for index, y in enumerate((245, 585, 925, 1265), 1):
        draw.rectangle((34, y, 565, y+318), outline=accent, width=2)
    draw.line((34, 1660, 566, 1660), fill=accent, width=2)
    draw.text((34, 1690), "SEOUL STEM FESTIVAL", fill=ink, font=font(22))
    overlay.save(folder / "overlay.png", dpi=(300, 300))
    preview = background.convert("RGBA")
    preview.alpha_composite(overlay)
    preview.convert("RGB").resize((180, 540), Image.Resampling.LANCZOS).save(folder / "thumbnail.png")


if __name__ == "__main__":
    generate("default-blue", "#e8e8e8", "#161616", "#777777")
    generate("default-light", "#ffffff", "#161616", "#aaaaaa")
