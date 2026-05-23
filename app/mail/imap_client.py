from __future__ import annotations

import email
import imaplib
from dataclasses import dataclass
from email.header import decode_header
from email.message import Message
from pathlib import Path
from typing import Iterable, List, Optional

from app.config import get_settings
from app.utils.file_utils import safe_filename


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

    def _connect(self) -> imaplib.IMAP4:
        if self.settings.imap_ssl:
            client = imaplib.IMAP4_SSL(self.settings.imap_host, self.settings.imap_port)
        else:
            client = imaplib.IMAP4(self.settings.imap_host, self.settings.imap_port)
        client.login(self.settings.imap_user, self.settings.imap_password)
        client.select(self.settings.imap_folder)
        return client

    def fetch_unseen_messages(self, since_uid: str | None = None) -> list[tuple[str, bytes]]:
        """
        Return raw RFC822 messages with UIDs greater than since_uid (if provided).
        """
        client = self._connect()
        try:
            criteria = ["ALL"]
            if self.settings.use_unread_only:
                criteria = ["UNSEEN"]
            if since_uid:
                criteria = [f"(UID {int(since_uid) + 1}:*)"]

            search_query = " ".join(criteria)
            status, data = client.uid("SEARCH", None, search_query)
            if status != "OK":
                return []

            uids = data[0].split()
            raw_messages: list[tuple[str, bytes]] = []
            for uid_bytes in uids:
                uid = uid_bytes.decode()
                status, msg_data = client.uid("FETCH", uid, "(RFC822)")
                if status != "OK" or not msg_data:
                    continue
                for item in msg_data:
                    if isinstance(item, tuple) and item[1]:
                        raw_messages.append((uid, item[1]))
                        break
            return raw_messages
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def parse_message(self, uid: str, raw: bytes) -> MailMessage:
        msg = email.message_from_bytes(raw)
        subject = _decode_header(msg.get("Subject"))
        sender = _decode_header(msg.get("From"))
        received_at = _decode_header(msg.get("Date"))
        body_text = _extract_text(msg)

        attachments: list[MailAttachment] = []
        for part in msg.walk():
            disposition = (part.get("Content-Disposition") or "").lower()
            filename = part.get_filename()
            if not filename or "attachment" not in disposition:
                continue

            decoded_filename = safe_filename(_decode_header(filename))
            payload = part.get_payload(decode=True) or b""
            attachment = MailAttachment(
                filename=decoded_filename,
                path=Path(decoded_filename),
                mime_type=part.get_content_type(),
                size_bytes=len(payload),
            )
            attachments.append(attachment)

        return MailMessage(
            uid=uid,
            subject=subject,
            sender=sender,
            received_at=received_at,
            body_text=body_text,
            attachments=attachments,
        )
