from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from app.config import get_settings
from app.mail.imap_client import MailMessage, MailAttachment
from app.utils.file_utils import (
    DOWNLOAD_DIR,
    detect_kind,
    ensure_directories,
    pdf_to_images,
    safe_filename,
    sha256_file,
    guess_mime_type,
)


@dataclass(slots=True)
class ParsedAttachment:
    original_name: str
    stored_path: Path
    mime_type: str
    kind: str
    sha256: str


@dataclass(slots=True)
class AttachmentBundle:
    files: list[ParsedAttachment]
    image_inputs: list[Path]
    source_pdf_pages: dict[str, list[Path]]


class AttachmentParser:
    def __init__(self):
        self.settings = get_settings()
        ensure_directories()

    def save_and_filter(self, message_uid: str, attachments: list[MailAttachment], raw_email_bytes: bytes | None = None) -> AttachmentBundle:
        message_dir = DOWNLOAD_DIR / f"mail_{message_uid}"
        message_dir.mkdir(parents=True, exist_ok=True)

        parsed: list[ParsedAttachment] = []
        image_inputs: list[Path] = []
        source_pdf_pages: dict[str, list[Path]] = {}

        for att in attachments:
            if att.path is None:
                continue
            ext = att.filename.lower().split(".")[-1] if "." in att.filename else ""
            allowed = self.settings.allowed_extensions()
            if f".{ext}" not in allowed:
                continue

            original_name = safe_filename(att.filename)
            stored_path = message_dir / original_name

            # The actual payload is extracted by caller; this module only manages paths.
            # A placeholder file is expected to exist already when the caller invokes this method.
            if stored_path.exists():
                kind = detect_kind(stored_path)
                sha256 = sha256_file(stored_path)
                mime_type = guess_mime_type(stored_path.name)

                parsed.append(
                    ParsedAttachment(
                        original_name=original_name,
                        stored_path=stored_path,
                        mime_type=mime_type,
                        kind=kind,
                        sha256=sha256,
                    )
                )

                if kind == "image":
                    image_inputs.append(stored_path)
                elif kind == "pdf":
                    pages = pdf_to_images(stored_path, max_pages=self.settings.max_pdf_pages)
                    source_pdf_pages[stored_path.name] = pages
                    image_inputs.extend(pages)

        return AttachmentBundle(files=parsed, image_inputs=image_inputs, source_pdf_pages=source_pdf_pages)

    def write_attachments_to_disk(self, message_uid: str, email_message, attachments_data: list[tuple[str, bytes, str]]) -> list[Path]:
        """
        Save raw attachment bytes to disk.
        attachments_data: list of (filename, payload_bytes, mime_type)
        """
        message_dir = DOWNLOAD_DIR / f"mail_{message_uid}"
        message_dir.mkdir(parents=True, exist_ok=True)

        saved_paths: list[Path] = []
        for filename, payload, mime_type in attachments_data:
            safe_name = safe_filename(filename)
            path = message_dir / safe_name
            path.write_bytes(payload)
            saved_paths.append(path)
        return saved_paths
