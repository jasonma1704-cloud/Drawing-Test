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
                self.imap.mark_as_read(uid)
            except Exception as exc:
                logger.exception("Failed processing message UID=%s", uid)
                self.db.log_event("error", f"Processing failed for UID={uid}", {"error": str(exc)})
                results.append(TaskResult(task_id=-1, status="failed", error=str(exc)))

        return results

    def process_single_message(self, uid: str, raw: bytes) -> TaskResult:
        # 1. 解析邮件
        mail = self.imap.parse_message(uid, raw)

        # 2. 创建任务
        task_id = self.db.upsert_task(
            message_uid=mail.uid,
            email_subject=mail.subject,
            sender=mail.sender,
            received_at=mail.received_at,
            attachment_count=len(mail.attachments),
            status="received",
        )

        # 3. 无附件直接跳过
        if not mail.attachments:
            msg = "No image or PDF attachment was found for AI analysis."
            self.db.update_task_status(task_id, "waiting_attachment", error=msg)
            return TaskResult(task_id=task_id, status="waiting_attachment", error=msg)

        # ======================
        # ✅ 核心修复：按时间戳保存附件（有附件才创建，不乱创建文件夹）
        # ======================
        bundle = self.parser.save_and_filter(mail.attachments, raw)

        # 4. 记录附件到数据库
        for att in bundle.files:
            kind = detect_kind(att.stored_path)
            self.db.add_attachment(
                task_id=task_id,
                filename=att.original_name,
                file_path=str(att.stored_path),
                mime_type=att.mime_type,
                kind=kind,
                sha256=sha256_file(att.stored_path),
            )

        # 5. 无有效图片 → 结束
        if not bundle.image_inputs:
            message = "No valid image/PDF for AI analysis."
            self.db.update_task_status(task_id, "waiting_attachment", error=message)
            return TaskResult(task_id=task_id, status="waiting_attachment", error=message)

        # 6. AI 解析
        image_paths = [str(p) for p in bundle.image_inputs]
        analysis = self.qwen.extract_structured_info(
            subject=mail.subject,
            sender=mail.sender,
            body_text=mail.body_text,
            image_paths=image_paths,
        )

        # 7. 推送飞书
        engineer_names = self._pick_engineers(analysis)
        feishu_summary = self._build_feishu_summary(mail.subject, mail.sender, analysis, bundle)
        push_text = self.feishu.build_text_message(mail.subject, feishu_summary, engineer_names)
        push_result = self.feishu.send_text(push_text)

        # 8. 更新任务状态
        final_status = "notified" if push_result.ok else "analysis_done"
        self.db.update_task_status(
            task_id,
            final_status,
            result=analysis,
            error=None if push_result.ok else "Feishu notification failed",
            feishu_sent=push_result.ok,
        )

        return TaskResult(task_id=task_id, status=final_status, result=analysis)

    async def polling_loop(self, stop_event: asyncio.Event | None = None) -> None:
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