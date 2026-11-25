"""Genera assets/sublab.ico: riquadro scuro arrotondato con box sottotitolo arancione."""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets", "sublab.ico")
SIZE = 256


def render(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=(21, 25, 34, 255))
    # bordo arancione del "box sottotitoli"
    pad = int(size * 0.16)
    box = [pad, int(size * 0.44), size - pad, size - int(size * 0.22)]
    d.rounded_rectangle(box, radius=int(size * 0.08), outline=(255, 170, 0, 255),
                        width=max(2, int(size * 0.055)))
    # due righe di "testo"
    lh = max(2, int(size * 0.045))
    y1 = box[1] + int((box[3] - box[1]) * 0.32)
    y2 = box[1] + int((box[3] - box[1]) * 0.66)
    d.rounded_rectangle([box[0] + int(size * 0.06), y1, box[2] - int(size * 0.20), y1 + lh],
                        radius=lh // 2, fill=(255, 255, 255, 235))
    d.rounded_rectangle([box[0] + int(size * 0.06), y2, box[2] - int(size * 0.34), y2 + lh],
                        radius=lh // 2, fill=(255, 255, 255, 170))
    return img


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    sizes = [256, 128, 64, 48, 32, 16]
    imgs = [render(s) for s in sizes]
    imgs[0].save(OUT, format="ICO", sizes=[(s, s) for s in sizes], append_images=imgs[1:])
    print("icona:", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
