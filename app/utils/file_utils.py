from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from PIL import Image

from app.config import DOWNLOAD_DIR, get_settings

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover - optional dependency
    fitz = None


@dataclass(slots=True)
class MediaFile:
    path: Path
    mime_type: str
    kind: str  # image, pdf, other


def ensure_directories() -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (Path(__file__).resolve().parents[2] / "logs").mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_filename(name: str) -> str:
    keep = []
    for ch in name.strip():
        if ch.isalnum() or ch in {"-", "_", ".", "(", ")", " ", "中", "文"}:
            keep.append(ch)
        else:
            keep.append("_")
    cleaned = "".join(keep).replace(" ", "_")
    return cleaned[:180] or "attachment"


def guess_mime_type(filename: str, fallback: str = "application/octet-stream") -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or fallback


def detect_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        return "image"
    if ext == ".pdf":
        return "pdf"
    return "other"


def path_to_data_url(path: Path) -> str:
    mime = guess_mime_type(path.name)
    data = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{data}"


def pdf_to_images(path: Path, max_pages: int | None = None) -> List[Path]:
    """
    Convert a PDF into page images. Requires PyMuPDF.
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF is not installed; PDF rendering is unavailable.")

    output_dir = path.parent / f"{path.stem}_pages"
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(path)
    images: List[Path] = []
    total_pages = len(doc)
    limit = min(total_pages, max_pages or total_pages)

    for index in range(limit):
        page = doc[index]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image_path = output_dir / f"{path.stem}_page_{index + 1}.png"
        pix.save(str(image_path))
        images.append(image_path)

    doc.close()
    return images


def make_thumbnail(path: Path, size: tuple[int, int] = (320, 240)) -> Path:
    thumb_dir = path.parent / "_thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumbnail_path = thumb_dir / f"{path.stem}.jpg"

    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail(size)
        img.save(thumbnail_path, format="JPEG", quality=85)
    return thumbnail_path
