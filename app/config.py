from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]
DOWNLOAD_DIR = BASE_DIR / "downloads"
LOG_DIR = BASE_DIR / "logs"
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "workflow.db"


class Settings(BaseSettings):
    """
    Runtime configuration.

    All secrets are read from environment variables or a local .env file.
    """

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Mail Workflow"
    environment: str = "production"
    poll_interval_seconds: int = 120

    # IMAP
    imap_host: str = Field(default="", alias="IMAP_HOST")
    imap_port: int = Field(default=993, alias="IMAP_PORT")
    imap_user: str = Field(default="", alias="IMAP_USER")
    imap_password: str = Field(default="", alias="IMAP_PASSWORD")
    imap_folder: str = Field(default="INBOX", alias="IMAP_FOLDER")
    imap_ssl: bool = Field(default=True, alias="IMAP_SSL")
    imap_sender_filter: str = Field(default="", alias="IMAP_SENDER_FILTER")

    # Qwen / DashScope compatible multimodal model
    qwen_api_key: str = Field(default="", alias="QWEN_API_KEY")
    qwen_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="QWEN_BASE_URL",
    )
    qwen_model: str = Field(default="qwen-vl-max-latest", alias="QWEN_MODEL")
    qwen_temperature: float = Field(default=0.0, alias="QWEN_TEMPERATURE")
    qwen_max_tokens: int = Field(default=1200, alias="QWEN_MAX_TOKENS")

    # Feishu webhook
    feishu_webhook_url: str = Field(default="", alias="FEISHU_WEBHOOK_URL")
    feishu_engineer_user_ids: str = Field(
        default="",
        alias="FEISHU_ENGINEER_USER_IDS",
        description="Comma-separated mapping in the form name:user_id,name2:user_id2",
    )

    # Workflow
    attachment_extensions: str = Field(
        default=".pdf,.png,.jpg,.jpeg,.webp",
        alias="ATTACHMENT_EXTENSIONS",
    )
    max_attachment_mb: int = Field(default=20, alias="MAX_ATTACHMENT_MB")
    max_pdf_pages: int = Field(default=5, alias="MAX_PDF_PAGES")
    use_unread_only: bool = Field(default=True, alias="USE_UNREAD_ONLY")
    mark_seen_after_success: bool = Field(default=False, alias="MARK_SEEN_AFTER_SUCCESS")

    @field_validator("attachment_extensions")
    @classmethod
    def _validate_extensions(cls, value: str) -> str:
        exts = [x.strip().lower() for x in value.split(",") if x.strip()]
        return ",".join(exts)

    def allowed_extensions(self) -> List[str]:
        return [x.strip().lower() for x in self.attachment_extensions.split(",") if x.strip()]

    def engineer_map(self) -> dict[str, str]:
        """
        Parse FEISHU_ENGINEER_USER_IDS=张三:ou_xxx,李四:ou_yyy
        """
        mapping: dict[str, str] = {}
        raw = self.feishu_engineer_user_ids.strip()
        if not raw:
            return mapping
        for item in raw.split(","):
            if ":" not in item:
                continue
            name, user_id = item.split(":", 1)
            name = name.strip()
            user_id = user_id.strip()
            if name and user_id:
                mapping[name] = user_id
        return mapping

    def engineer_names(self) -> List[str]:
        return list(self.engineer_map().keys())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
