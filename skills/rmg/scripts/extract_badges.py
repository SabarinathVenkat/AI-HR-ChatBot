"""Take the small pictures (certification badges) out of the header of a candidate's Word resume.

The template has its own logo and banner, so the candidate's pictures would be lost when the resume is rebuilt. This saves them
as clean PNG files so RMG can choose which to keep, and place_badges.py can put them in the finished file.

What counts as a badge: a picture placed *inline* (not floating, which is how a banner or logo is placed) in the first table of
the document (the header), between 24 and 240 pixels on the page. At most 6. Each is checked and re-drawn as a plain PNG, which
drops any hidden data in the file. A photo of the candidate looks the same as a badge, so ALWAYS ask RMG which to keep.

Usage:
  python extract_badges.py <resume.docx> <output folder>
Writes badge1.png, badge2.png ... and prints one line per picture: file name, size and the author's alt text if any.
Prints "no badges" if there are none. A file that cannot be read has no badges; this never stops the work.
Needs Pillow and lxml (both are there with python-docx).
"""
import hashlib
import io
import posixpath
import re
import sys
import zipfile
from pathlib import Path

MAX_BADGES = 6
MAX_SOURCE_BYTES = 2_000_000
MAX_PIXELS = 25_000_000
MIN_SIDE, MAX_SIDE = 24, 240
STORE_SIDE = 400
EMU_PER_PIXEL = 9525

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def clean_picture(data: bytes) -> bytes | None:
    """A plain PNG made from `data`, or None if it is not a real, reasonably sized PNG or JPEG."""
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(data))
        if image.format not in ("PNG", "JPEG"):
            return None
        if image.width * image.height > MAX_PIXELS or min(image.size) < 1:
            return None
        image.load()
        image = image.convert("RGBA")
        image.thumbnail((STORE_SIDE, STORE_SIDE))
        out = io.BytesIO()
        image.save(out, "PNG")
        return out.getvalue()
    except Exception:  # noqa: BLE001 - a picture that cannot be read safely is simply not used
        return None


def _parser():
    from lxml import etree

    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False)


def _targets(archive: zipfile.ZipFile) -> dict[str, str]:
    """relationship id -> path of an image inside the file (only word/media/ files)."""
    from lxml import etree

    out: dict[str, str] = {}
    root = etree.fromstring(archive.read("word/_rels/document.xml.rels"), _parser())
    names = set(archive.namelist())
    for rel in root.iter(f"{{{REL}}}Relationship"):
        if rel.get("TargetMode") == "External" or not rel.get("Type", "").endswith("/image"):
            continue
        path = posixpath.normpath(posixpath.join("word", rel.get("Target", "")))
        if path.startswith("word/media/") and path in names:
            out[rel.get("Id")] = path
    return out


def extract(path: str) -> list[tuple[bytes, str | None]]:
    """(png bytes, alt text) for each badge, in document order. Never raises."""
    from lxml import etree

    try:
        archive = zipfile.ZipFile(path)
        targets = _targets(archive)
        body = etree.fromstring(archive.read("word/document.xml"), _parser()).find(f"{{{W}}}body")
        table = body.find(f"{{{W}}}tbl") if body is not None else None
        if table is None:
            return []
        found: list[tuple[bytes, str | None]] = []
        seen: set[str] = set()
        for inline in table.iter(f"{{{WP}}}inline"):
            if len(found) >= MAX_BADGES:
                break
            extent = inline.find(f"{{{WP}}}extent")
            blip = inline.find(f".//{{{A}}}blip")
            if extent is None or blip is None:
                continue
            width, height = int(extent.get("cx", 0)) // EMU_PER_PIXEL, int(extent.get("cy", 0)) // EMU_PER_PIXEL
            if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE):
                continue
            name = targets.get(blip.get(f"{{{R}}}embed"))
            if name is None or archive.getinfo(name).file_size > MAX_SOURCE_BYTES:
                continue
            png = clean_picture(archive.read(name))
            if png is None:
                continue
            digest = hashlib.sha256(png).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            properties = inline.find(f"{{{WP}}}docPr")
            text = (properties.get("descr") or properties.get("title")) if properties is not None else None
            label = " ".join(_CONTROL.sub(" ", text or "").split())[:120].strip() or None
            found.append((png, label))
        return found
    except Exception:  # noqa: BLE001
        return []


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("Usage: python extract_badges.py <resume.docx> <output folder>", file=sys.stderr)
        return 2
    source, folder = args
    if not source.lower().endswith(".docx"):
        print("no badges (only Word .docx resumes are read for pictures)")
        return 0
    badges = extract(source)
    if not badges:
        print("no badges")
        return 0
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    for n, (png, label) in enumerate(badges, 1):
        target = out / f"badge{n}.png"
        target.write_bytes(png)
        print(f"{target.name}\t{len(png)} bytes\talt text: {label or '(none)'}")
    print(f"{len(badges)} picture(s) found. Ask RMG which to keep: a photo of the candidate looks like a badge.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
