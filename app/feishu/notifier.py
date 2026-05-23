from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Iterable

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FeishuNotificationResult:
    ok: bool
    status_code: int | None = None
    response_text: str | None = None


class FeishuNotifier:
    """
    Push workflow results to a Feishu custom bot webhook.
    """
    def __init__(self):
        self.settings = get_settings()

    def _mention_tag(self, name: str, user_id: str | None) -> str:
        if user_id:
            return f'<at user_id="{user_id}">{name}</at>'
        return name

    def build_text_message(self, title: str, summary: str, engineer_names: list[str]) -> str:
        engineer_map = self.settings.engineer_map()
        mentions = [
            self._mention_tag(name, engineer_map.get(name))
            for name in engineer_names
            if name in engineer_map
        ]
        mention_text = " ".join(mentions) if mentions else "工程师"
        lines = [
            f"【询价提醒】{title}",
            "",
            summary,
            "",
            f"请相关同事查看：{mention_text}",
        ]
        return "\n".join(lines)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def send_text(self, content: str) -> FeishuNotificationResult:
        if not self.settings.feishu_webhook_url:
            raise RuntimeError("FEISHU_WEBHOOK_URL is not configured.")
        payload = {
            "msg_type": "text",
            "content": {"text": content},
        }
        resp = requests.post(self.settings.feishu_webhook_url, json=payload, timeout=15)
        ok = resp.ok
        if not ok:
            logger.error("Feishu send failed: %s %s", resp.status_code, resp.text[:500])
        return FeishuNotificationResult(ok=ok, status_code=resp.status_code, response_text=resp.text)
