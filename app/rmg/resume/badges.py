"""Badges: the small pictures a candidate keeps in the header of their resume, such as certification badges.

The builder reads a resume's text only, so these pictures would be lost on download. This module finds them in an uploaded
Word file so they can be offered to the associate and placed in the template's header cell on download.

What counts as a badge: a picture that sits *inline* (not floating behind the text, which is how a banner or the company logo
is placed) inside the first table of the document (the header), and is between 24 and 240 pixels on the page. At most
MAX_BADGES, each one once.

The file is untrusted, so nothing is passed on as it came. Each picture must be a real PNG or JPEG within size and pixel limits
(so a decompression bomb is refused), and is re-encoded as a plain PNG no larger than STORE_SIDE pixels, which drops any hidden
data. A photo of the candidate is not told apart from a badge by the code, which is why the associate confirms every picture
and can remove it.
"""
import base64
import hashlib
import io
import posixpath
import re
import zipfile
from dataclasses import dataclass

from lxml import etree
from PIL import Image

MAX_BADGES = 6
MAX_SOURCE_BYTES = 2_000_000  # one picture as stored in the file, before decoding
MAX_PIXELS = 25_000_000  # a picture bigger than this (width x height) is refused before it is decoded
MIN_SIDE, MAX_SIDE = 24, 240  # size on the page, in pixels at 96 dpi
STORE_SIDE = 400  # the longest side of the re-encoded picture
THUMB_SIDE = 96
EMU_PER_PIXEL = 9525
LABEL_CHARS = 120

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class RawBadge:
    png: bytes  # re-encoded, at most STORE_SIDE pixels on a side
    label: str | None  # the picture's alt text, if the author gave it one


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False)


def clean_picture(data: bytes) -> bytes | None:
    """A plain PNG made from `data`, or None if it is not a real, reasonably sized PNG or JPEG."""
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
    except Exception:  # noqa: BLE001 - any picture that cannot be read safely is simply not used
        return None


def _label(description: str | None) -> str | None:
    text = " ".join(_CONTROL.sub(" ", description or "").split())[:LABEL_CHARS].strip()
    return text or None


def extract_badges(docx: bytes) -> list[RawBadge]:
    """The badges in an uploaded Word file, in document order. Never raises: a file that cannot be read has no badges."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(docx))
        targets = _targets(archive)
        body = etree.fromstring(archive.read("word/document.xml"), _parser()).find(f"{{{W}}}body")
        table = body.find(f"{{{W}}}tbl") if body is not None else None  # the first table: the header
        if table is None:
            return []
        found: list[RawBadge] = []
        seen: set[str] = set()
        for inline in table.iter(f"{{{WP}}}inline"):  # floating pictures (banners, the logo) are "anchor" elements and are skipped
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
            found.append(RawBadge(png=png, label=_label(properties.get("descr") or properties.get("title") if properties is not None else None)))
        return found
    except Exception:  # noqa: BLE001 - badges are a courtesy: a damaged file must not stop an upload or a build
        return []


def _targets(archive: zipfile.ZipFile) -> dict[str, str]:
    """relationship id -> the path of an image inside the file (only word/media/ files)."""
    out: dict[str, str] = {}
    root = etree.fromstring(archive.read("word/_rels/document.xml.rels"), _parser())
    for rel in root.iter(f"{{{REL}}}Relationship"):
        if rel.get("TargetMode") == "External" or not rel.get("Type", "").endswith("/image"):
            continue
        path = posixpath.normpath(posixpath.join("word", rel.get("Target", "")))
        if path.startswith("word/media/") and path in archive.namelist():
            out[rel.get("Id")] = path
    return out


def thumbnail_data_url(png: bytes) -> str | None:
    """A small picture as a data: address, for showing on the page without a separate request."""
    try:
        image = Image.open(io.BytesIO(png))
        image.thumbnail((THUMB_SIDE, THUMB_SIDE))
        out = io.BytesIO()
        image.save(out, "PNG")
        return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001
        return None
