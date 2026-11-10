"""Draw the Khmer Dub app icon: the episode weft band (dyed line blocks) on indigo.

Run:  uv run --extra cpu python scripts/make_icon.py
Writes src/khmerdub/assets/icon.png (512 px), icon.ico (Windows) and icon.icns (macOS).
Colours come from DESIGN.md: rail indigo, lac (Sreymom), sky-indigo (Piseth), turmeric (current line).
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "src" / "khmerdub" / "assets"
RAIL, GROUND, RULE = (27, 33, 71), (16, 20, 58), (52, 60, 116)
LAC, SKY, TUR = (201, 56, 77), (95, 128, 230), (232, 166, 42)

# blocks as (relative width, colour or None for a gap), like a short stretch of dialogue
BLOCKS = [(2, SKY), (0.6, None), (3.4, LAC), (0.5, None), (1.6, SKY), (2.6, LAC), (0.8, None), (3.2, TUR),
          (0.6, None), (2.2, SKY), (1.4, LAC), (0.5, None), (2.8, SKY), (0.7, None), (1.8, LAC)]


def draw(size: int = 1024) -> Image.Image:
    img = Image.new("RGB", (size, size), RAIL)
    d = ImageDraw.Draw(img)
    pad = 0  # the band runs edge to edge, like a strip of the episode
    top, bottom = round(size * 0.27), round(size * 0.73)
    d.rectangle([0, top, size, bottom], fill=GROUND)
    total = sum(w for w, _ in BLOCKS)
    x = float(pad)
    span = size - 2 * pad
    for w, colour in BLOCKS:
        x1 = x + span * w / total
        if colour:
            d.rectangle([round(x), top, round(x1) - 1, bottom], fill=colour)
            # weft threads: thin darker lines across each dyed block
            step = max(3, size // 96)
            for y in range(top, bottom, step):
                d.line([round(x), y, round(x1) - 1, y], fill=tuple(int(c * 0.82) for c in colour),
                       width=max(1, size // 512))
        x = x1
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = draw(1024)
    big.resize((512, 512), Image.LANCZOS).save(OUT / "icon.png", optimize=True)
    big.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(OUT / "icon.icns")
    print("wrote", ", ".join(p.name for p in sorted(OUT.glob("icon.*"))))


if __name__ == "__main__":
    main()
