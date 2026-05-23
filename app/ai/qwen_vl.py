from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.ai.prompt import EXTRACTION_PROMPT, build_email_context_prompt
from app.utils.file_utils import path_to_data_url

logger = logging.getLogger(__name__)


class QwenVLClient:
    """
    OpenAI-compatible client for Qwen multimodal models.
    """

    def __init__(self):
        self.settings = get_settings()
        self.client = OpenAI(
            api_key=self.settings.qwen_api_key,
            base_url=self.settings.qwen_base_url,
        )

    def _build_messages(self, subject: str, sender: str, body_text: str, image_paths: list[str]) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": EXTRACTION_PROMPT}]
        content.append({"type": "text", "text": build_email_context_prompt(subject, sender, body_text)})
        for path in image_paths:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": path_to_data_url(Path(path))},
                }
            )
        return [{"role": "user", "content": content}]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def extract_structured_info(
        self,
        subject: str,
        sender: str,
        body_text: str,
        image_paths: list[str],
    ) -> dict[str, Any]:
        if not self.settings.qwen_api_key:
            raise RuntimeError("QWEN_API_KEY is not configured.")
        if not image_paths:
            raise RuntimeError("No image inputs were provided for Qwen-VL.")

        response = self.client.chat.completions.create(
            model=self.settings.qwen_model,
            messages=self._build_messages(subject, sender, body_text, image_paths),
            temperature=self.settings.qwen_temperature,
            max_tokens=self.settings.qwen_max_tokens,
        )

        text = response.choices[0].message.content or ""
        return self._parse_json(text)

    def _parse_json(self, text: str) -> dict[str, Any]:
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if "\n" in raw:
                raw = raw.split("\n", 1)[1]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(raw[start : end + 1])
            raise
