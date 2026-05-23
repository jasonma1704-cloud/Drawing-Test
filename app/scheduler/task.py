from __future__ import annotations

import logging
from dataclasses import dataclass
import asyncio
from pathlib import Path
from typing import Any

from app.ai.qwen_vl import QwenVLClient
from app.config import get_settings
from app.feishu.notifier import FeishuNotifier
from app.mail.attachment_parser import AttachmentParser
from app.mail.imap_client import ImapClient
from app.storage.db import Database
from app.utils.file_utils import detect_kind, guess_mime_type, sha256_file

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TaskResult:
    task_id: int
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None


class WorkflowEngine:
    def __init__(self, db: Database | None = None):
        self.settings = get_settings()
        self.db = db or Database()
        self.imap = ImapClient()
        self.parser = AttachmentParser()
        self.qwen = QwenVLClient()
        self.feishu = FeishuNotifier()

    def fetch_and_process_once(self) -> list[TaskResult]:
        """
        Fetch new emails, process each one, and push notifications.
        """
        last_uid = self.db.get_last_uid()
        raw_messages = self.imap.fetch_unseen_messages(last_uid)
        results: list[TaskResult] = []

        if not raw_messages:
            self.db.log_event("info", "No new email messages found", {"last_uid": last_uid})
            return results

        for uid, raw in raw_messages:
            try:
                result = self.process_single_message(uid, raw)
                results.append(result)
                self.db.set_last_uid(uid)
            except Exception as exc:
                logger.exception("Failed processing message UID=%s", uid)
                self.db.log_event("error", f"Processing failed for UID={uid}", {"error": str(exc)})
                results.append(TaskResult(task_id=-1, status="failed", error=str(exc)))

        return results

    def process_single_message(self, uid: str, raw: bytes) -> TaskResult:
        mail = self.imap.parse_message(uid, raw)
        task_id = self.db.upsert_task(
            message_uid=mail.uid,
            email_subject=mail.subject,
            sender=mail.sender,
            received_at=mail.received_at,
            attachment_count=len(mail.attachments),
            status="received",
        )

        attachments_data: list[tuple[str, bytes, str]] = []
        import email as _email
        message = _email.message_from_bytes(raw)
        max_bytes = self.settings.max_attachment_mb * 1024 * 1024
        for part in message.walk():
            disposition = (part.get("Content-Disposition") or "").lower()
            filename = part.get_filename()
            if not filename or "attachment" not in disposition:
                continue
            payload = part.get_payload(decode=True) or b""
            if len(payload) > max_bytes:
                logger.warning("Skip oversized attachment: %s (%s bytes)", filename, len(payload))
                continue
            attachments_data.append((filename, payload, part.get_content_type()))

        saved_paths = self.parser.write_attachments_to_disk(mail.uid, message, attachments_data)
        bundle = self.parser.save_and_filter(
            mail.uid,
            mail.attachments,
        )

        for path in saved_paths:
            kind = detect_kind(path)
            self.db.add_attachment(
                task_id=task_id,
                filename=path.name,
                file_path=str(path),
                mime_type=guess_mime_type(path.name),
                kind=kind,
                sha256=sha256_file(path),
            )

        if not bundle.image_inputs:
            message = "No image or PDF attachment was found for AI analysis."
            self.db.update_task_status(task_id, "waiting_attachment", error=message)
            return TaskResult(task_id=task_id, status="waiting_attachment", error=message)

        image_paths = [str(p) for p in bundle.image_inputs]
        analysis = self.qwen.extract_structured_info(
            subject=mail.subject,
            sender=mail.sender,
            body_text=mail.body_text,
            image_paths=image_paths,
        )

        engineer_names = self._pick_engineers(analysis)
        feishu_summary = self._build_feishu_summary(mail.subject, mail.sender, analysis, bundle)
        push_text = self.feishu.build_text_message(mail.subject, feishu_summary, engineer_names)
        push_result = self.feishu.send_text(push_text)

        final_status = "notified" if push_result.ok else "analysis_done"
        self.db.update_task_status(
            task_id,
            final_status,
            result=analysis,
            error=None if push_result.ok else "Feishu notification failed",
            feishu_sent=push_result.ok,
        )

        if self.settings.mark_seen_after_success:
            self.db.set_last_uid(uid)

        return TaskResult(task_id=task_id, status=final_status, result=analysis)


    async def polling_loop(self, stop_event: asyncio.Event | None = None) -> None:
        """
        Background polling loop. It can be started from FastAPI startup.
        """
        interval = max(10, int(self.settings.poll_interval_seconds))
        stop_event = stop_event or asyncio.Event()
        logger.info("Polling loop started with interval=%ss", interval)
        while not stop_event.is_set():
            try:
                await asyncio.to_thread(self.fetch_and_process_once)
            except Exception:
                logger.exception("Polling loop failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue
        logger.info("Polling loop stopped")

    def _pick_engineers(self, analysis: dict[str, Any]) -> list[str]:
        engineers = self.settings.engineer_names()
        if not engineers:
            return []
        # Simple but practical heuristic: always notify the first configured engineer.
        # In production you can map by product line, material, or drawing type.
        return engineers[:1]

    def _build_feishu_summary(
        self,
        subject: str,
        sender: str,
        analysis: dict[str, Any],
        bundle,
    ) -> str:
        summary = analysis.get("summary") or ""
        lines = [
            f"邮件主题：{subject}",
            f"发件人：{sender}",
            f"识别摘要：{summary}",
        ]
        if analysis.get("part_number"):
            lines.append(f"图号：{analysis['part_number']}")
        if analysis.get("material"):
            lines.append(f"材料：{analysis['material']}")
        if analysis.get("quantity"):
            lines.append(f"数量：{analysis['quantity']}")
        lines.append(f"附件张数：{len(bundle.image_inputs)}")
        return "\n".join(lines)
