import logging
from pathlib import Path
from datetime import datetime
import email

from app.config import get_settings
from app.utils.file_utils import (
    safe_filename,
    detect_kind,
    sha256_file,
    guess_mime_type,
    pdf_to_images,
    ensure_directories
)
from app.mail.imap_client import MailAttachment, _decode_header

logger = logging.getLogger(__name__)
settings = get_settings()
DOWNLOAD_DIR = Path("attachments")


class ParsedAttachment:
    def __init__(self, original_name, stored_path, mime_type, kind, sha256):
        self.original_name = original_name
        self.stored_path = stored_path
        self.mime_type = mime_type
        self.kind = kind
        self.sha256 = sha256


class AttachmentBundle:
    def __init__(self, files=None, image_inputs=None, source_pdf_pages=None):
        self.files = files or []
        self.image_inputs = image_inputs or []
        self.source_pdf_pages = source_pdf_pages or {}


class AttachmentParser:
    def __init__(self):
        ensure_directories()

    def save_and_filter(self, attachments: list[MailAttachment], raw_email_bytes: bytes) -> AttachmentBundle:
        if not attachments:
            logger.info("ℹ️ 无附件，跳过保存")
            return AttachmentBundle()

        # ======================
        # 时间戳文件夹（精确到分）
        # ======================
        time_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_dir = DOWNLOAD_DIR / time_tag
        save_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"📂 附件将保存到: {save_dir.absolute()}")

        parsed = []
        images = []
        pdf_pages = {}

        for att in attachments:
            ext = att.filename.lower().split(".")[-1] if "." in att.filename else ""
            allowed = settings.allowed_extensions()
            if f".{ext}" not in allowed:
                logger.info(f"⚠️ 格式不支持，跳过: {att.filename}")
                continue

            save_path = save_dir / att.filename

            # 从邮件原始数据读取并写入文件
            msg = email.message_from_bytes(raw_email_bytes)
            for part in msg.walk():
                fn = part.get_filename()
                if fn and safe_filename(_decode_header(fn)) == att.filename:
                    payload = part.get_payload(decode=True) or b""
                    save_path.write_bytes(payload)
                    logger.info(f"✅ 已保存: {save_path.name}")
                    break

            if not save_path.exists():
                continue

            kind = detect_kind(save_path)
            sha256 = sha256_file(save_path)
            mime = guess_mime_type(save_path.name)

            parsed.append(ParsedAttachment(
                original_name=att.filename,
                stored_path=save_path,
                mime_type=mime,
                kind=kind,
                sha256=sha256
            ))

            if kind == "image":
                images.append(save_path)
            elif kind == "pdf":
                pages = pdf_to_images(save_path, settings.max_pdf_pages)
                pdf_pages[save_path.name] = pages
                images.extend(pages)

        return AttachmentBundle(
            files=parsed,
            image_inputs=images,
            source_pdf_pages=pdf_pages
        )