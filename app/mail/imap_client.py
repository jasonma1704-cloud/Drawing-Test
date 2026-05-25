from __future__ import annotations

import email
import imaplib
import logging
from dataclasses import dataclass
from email.header import decode_header
from email.message import Message
from pathlib import Path
from typing import List
from datetime import datetime

from app.config import get_settings
from app.utils.file_utils import safe_filename

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MailAttachment:
    filename: str
    path: Path
    mime_type: str | None
    size_bytes: int


@dataclass(slots=True)
class MailMessage:
    uid: str
    subject: str
    sender: str
    received_at: str
    body_text: str
    attachments: list[MailAttachment]


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for text, charset in parts:
        if isinstance(text, bytes):
            decoded.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(text)
    return "".join(decoded)


def _extract_text(message: Message) -> str:
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = (part.get("Content-Disposition") or "").lower()
            if content_type == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        payload = message.get_payload(decode=True)
        if payload:
            return payload.decode(message.get_content_charset() or "utf-8", errors="replace")
    return ""


class ImapClient:
    def __init__(self):
        self.settings = get_settings()
        logger.info("✅ IMAP 客户端初始化完成")

    def _connect(self) -> imaplib.IMAP4:
        imap_host = "imap.qq.com"
        imap_port = 993
        logger.info(f"🔌 连接邮箱: {imap_host}:{imap_port}")

        try:
            if self.settings.imap_ssl:
                client = imaplib.IMAP4_SSL(imap_host, imap_port)
            else:
                client = imaplib.IMAP4(imap_host, imap_port)

            client.login(self.settings.imap_user, self.settings.imap_password)
            client.select(self.settings.imap_folder)
            logger.info("✅ 登录成功，文件夹: %s", self.settings.imap_folder)
            return client
        except Exception as e:
            logger.error("❌ 连接失败: %s", str(e))
            raise

    def fetch_unseen_messages(self, since_uid: str | None = None) -> list[tuple[str, bytes]]:
        logger.info("🔍 开始获取邮件...")
        client = self._connect()
        try:
            criteria = ["UNSEEN"]
            if since_uid:
                criteria = [f"(UID {int(since_uid) + 1}:*)"]

            status, data = client.uid("SEARCH", None, " ".join(criteria))
            if status != "OK":
                return []

            uids = data[0].split()
            logger.info(f"📥 未读邮件数量: {len(uids)}")

            raw_messages = []
            for uid_bytes in uids:
                uid = uid_bytes.decode()
                status, msg_data = client.uid("FETCH", uid, "(RFC822)")
                if status != "OK" or not msg_data:
                    continue
                for item in msg_data:
                    if isinstance(item, tuple) and item[1]:
                        raw_messages.append((uid, item[1]))
                        logger.info(f"✅ 获取邮件 UID: {uid}")
                        break
            return raw_messages
        finally:
            try:
                client.logout()
                logger.info("🔌 已断开邮箱")
            except Exception:
                pass

    def mark_as_read(self, uid: str) -> None:
        """
        新增核心功能：标记邮件为已读
        处理完成后调用，彻底避免重复扫描、重复处理
        """
        client = self._connect()
        try:
            # 标记邮件为已读 (Seen)
            client.uid("STORE", uid, "+FLAGS", "(\\Seen)")
            logger.info(f"✅ 已标记邮件为已读 UID: {uid}")
        except Exception as e:
            logger.error(f"❌ 标记邮件已读失败 UID {uid}: {str(e)}")
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def parse_message(self, uid: str, raw: bytes) -> MailMessage:
        logger.info(f"📝 解析邮件 UID: {uid}")
        msg = email.message_from_bytes(raw)
        subject = _decode_header(msg.get("Subject"))
        sender = _decode_header(msg.get("From"))
        received_at = _decode_header(msg.get("Date"))
        body_text = _extract_text(msg)

        logger.info(f"📩 主题: {subject}")
        logger.info(f"📤 发件人: {sender}")

        attachments = []
        for part in msg.walk():
            filename = part.get_filename()
            if not filename:
                continue

            try:
                decoded_fn = safe_filename(_decode_header(filename))
                payload = part.get_payload(decode=True) or b""
                size = len(payload)

                attachment = MailAttachment(
                    filename=decoded_fn,
                    path=Path(decoded_fn),
                    mime_type=part.get_content_type(),
                    size_bytes=size
                )
                attachments.append(attachment)
                logger.info(f"📎 发现附件: {decoded_fn}")

            except Exception as e:
                logger.error(f"❌ 解析附件失败: {filename} => {e}")
                continue

        logger.info(f"✅ 解析完成，附件数: {len(attachments)}")
        return MailMessage(
            uid=uid,
            subject=subject,
            sender=sender,
            received_at=received_at,
            body_text=body_text,
            attachments=attachments
        )