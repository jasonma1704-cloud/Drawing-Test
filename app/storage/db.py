from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from app.config import DB_PATH


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_uid TEXT UNIQUE,
                    email_subject TEXT,
                    sender TEXT,
                    received_at TEXT,
                    attachment_count INTEGER DEFAULT 0,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    feishu_sent INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    mime_type TEXT,
                    kind TEXT,
                    sha256 TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mail_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_uid TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO mail_state (id, last_uid, updated_at) VALUES (1, NULL, ?)",
                (utc_now(),),
            )

    def log_event(self, level: str, message: str, payload: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO app_events (level, message, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (level, message, json.dumps(payload, ensure_ascii=False) if payload else None, utc_now()),
            )

    def get_last_uid(self) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT last_uid FROM mail_state WHERE id = 1").fetchone()
            return row["last_uid"] if row else None

    def set_last_uid(self, uid: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE mail_state SET last_uid = ?, updated_at = ? WHERE id = 1",
                (uid, utc_now()),
            )

    def upsert_task(
        self,
        message_uid: str,
        email_subject: str,
        sender: str,
        received_at: str,
        attachment_count: int,
        status: str,
        error: str | None = None,
    ) -> int:
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM tasks WHERE message_uid = ?",
                (message_uid,),
            ).fetchone()
            if existing:
                task_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE tasks
                    SET email_subject = ?, sender = ?, received_at = ?, attachment_count = ?,
                        status = ?, error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        email_subject,
                        sender,
                        received_at,
                        attachment_count,
                        status,
                        error,
                        utc_now(),
                        task_id,
                    ),
                )
                return task_id

            cursor = conn.execute(
                """
                INSERT INTO tasks (
                    message_uid, email_subject, sender, received_at, attachment_count,
                    status, error, feishu_sent, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    message_uid,
                    email_subject,
                    sender,
                    received_at,
                    attachment_count,
                    status,
                    error,
                    utc_now(),
                    utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def update_task_status(
        self,
        task_id: int,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        feishu_sent: bool | None = None,
    ) -> None:
        with self.connect() as conn:
            current = conn.execute("SELECT result_json, feishu_sent FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not current:
                return
            result_json = json.dumps(result, ensure_ascii=False) if result is not None else current["result_json"]
            sent = int(feishu_sent) if feishu_sent is not None else int(current["feishu_sent"] or 0)
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, result_json = ?, error = ?, feishu_sent = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, result_json, error, sent, utc_now(), task_id),
            )

    def add_attachment(
        self,
        task_id: int,
        filename: str,
        file_path: str,
        mime_type: str | None,
        kind: str | None,
        sha256: str | None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO attachments (
                    task_id, filename, file_path, mime_type, kind, sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, filename, file_path, mime_type, kind, sha256, utc_now()),
            )

    def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, message_uid, email_subject, sender, received_at, attachment_count,
                       status, result_json, error, feishu_sent, created_at, updated_at
                FROM tasks
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, message_uid, email_subject, sender, received_at, attachment_count,
                       status, result_json, error, feishu_sent, created_at, updated_at
                FROM tasks WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_attachments(self, task_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM attachments WHERE task_id = ? ORDER BY id ASC",
                (task_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM app_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
