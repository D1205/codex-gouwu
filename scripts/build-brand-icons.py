"""Render the project's simple SVG mark using Pillow, a build-time dependency.

The SVG is the source of truth. This deliberately supports only the elements used
by the mark, and fails if its vocabulary changes instead of silently omitting art.
"""
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw


PROJECT = Path(__file__).resolve().parent.parent
BRAND = PROJECT / "ui/public/brand"
SOURCE = BRAND / "logo.svg"


def render(size: int) -> Image.Image:
    root = ET.parse(SOURCE).getroot()
    scale = size * 4 / 64
    image = Image.new("RGBA", (size * 4, size * 4))
    draw = ImageDraw.Draw(image)
    for element in root:
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "title":
            continue
        if tag == "rect":
            x = float(element.get("x", 0)) * scale
            y = float(element.get("y", 0)) * scale
            w = float(element.attrib["width"]) * scale
            h = float(element.attrib["height"]) * scale
            draw.rounded_rectangle((x, y, x + w, y + h),
                                   radius=float(element.get("rx", 0)) * scale,
                                   fill=element.attrib["fill"])
        elif tag == "polyline":
            points = [tuple(float(value) * scale for value in pair.split(","))
                      for pair in element.attrib["points"].split()]
            color = element.attrib["stroke"]
            width = float(element.attrib["stroke-width"]) * scale
            draw.line(points, fill=color, width=round(width), joint="curve")
            radius = width / 2
            for x, y in points:
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
        else:
            raise ValueError(f"Unsupported brand SVG element: {tag}")
    return image.resize((size, size), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    shutil.copyfile(SOURCE, PROJECT / "ui/public/favicon.svg")
    render(256).save(BRAND / "app-256.png")
    sizes = (16, 20, 24, 32, 40, 48, 64, 128, 256)
    render(256).save(BRAND / "app.ico", sizes=[(size, size) for size in sizes],
                     append_images=[render(size) for size in sizes[:-1]])
    print("Generated favicon.svg, app-256.png and app.ico (16–256 px).")
