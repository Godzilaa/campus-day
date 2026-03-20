import sqlite3
from pathlib import Path
from typing import Iterable


class Storage:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS roles (
                    chat_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    username TEXT,
                    role TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    assignee_user_id TEXT,
                    assignee_username TEXT,
                    due_date TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS meeting_sessions (
                    chat_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    started_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS meeting_transcripts (
                    chat_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, session_id)
                );
                """
            )

    def upsert_role(
        self,
        chat_id: str,
        user_id: str,
        username: str | None,
        role: str,
        updated_at: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO roles (chat_id, user_id, username, role, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, user_id)
                DO UPDATE SET username = excluded.username, role = excluded.role, updated_at = excluded.updated_at
                """,
                (chat_id, user_id, username, role, updated_at),
            )

    def get_role(self, chat_id: str, user_id: str):
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM roles WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            return cur.fetchone()

    def list_roles(self, chat_id: str) -> Iterable[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM roles WHERE chat_id = ? ORDER BY updated_at DESC",
                (chat_id,),
            )
            return cur.fetchall()

    def create_task(
        self,
        chat_id: str,
        title: str,
        assignee_user_id: str | None,
        assignee_username: str | None,
        due_date: str | None,
        created_at: str,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO tasks (chat_id, title, assignee_user_id, assignee_username, due_date, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'open', ?)
                """,
                (chat_id, title, assignee_user_id, assignee_username, due_date, created_at),
            )
            return int(cur.lastrowid)

    def complete_task(self, chat_id: str, task_id: int, completed_at: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE tasks
                SET status = 'done', completed_at = ?
                WHERE chat_id = ? AND id = ? AND status != 'done'
                """,
                (completed_at, chat_id, task_id),
            )
            return cur.rowcount > 0

    def list_open_tasks(self, chat_id: str) -> Iterable[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT * FROM tasks
                WHERE chat_id = ? AND status = 'open'
                ORDER BY CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date ASC, id ASC
                """,
                (chat_id,),
            )
            return cur.fetchall()

    def list_due_tasks(self, iso_date: str) -> Iterable[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status = 'open' AND due_date IS NOT NULL AND due_date <= ?
                ORDER BY due_date ASC, id ASC
                """,
                (iso_date,),
            )
            return cur.fetchall()

    def set_active_session(self, chat_id: str, session_id: str, started_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO meeting_sessions (chat_id, session_id, started_at)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id)
                DO UPDATE SET session_id = excluded.session_id, started_at = excluded.started_at
                """,
                (chat_id, session_id, started_at),
            )

    def get_active_session(self, chat_id: str):
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM meeting_sessions WHERE chat_id = ?",
                (chat_id,),
            )
            return cur.fetchone()

    def clear_active_session(self, chat_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM meeting_sessions WHERE chat_id = ?", (chat_id,))

    def append_transcript_line(
        self,
        chat_id: str,
        session_id: str,
        line: str,
        updated_at: str,
    ) -> str:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT content
                FROM meeting_transcripts
                WHERE chat_id = ? AND session_id = ?
                """,
                (chat_id, session_id),
            )
            row = cur.fetchone()
            if row is None:
                content = line
                conn.execute(
                    """
                    INSERT INTO meeting_transcripts (chat_id, session_id, content, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (chat_id, session_id, content, updated_at),
                )
            else:
                content = f"{row['content']}\n{line}"
                conn.execute(
                    """
                    UPDATE meeting_transcripts
                    SET content = ?, updated_at = ?
                    WHERE chat_id = ? AND session_id = ?
                    """,
                    (content, updated_at, chat_id, session_id),
                )
            return content

    def get_transcript(self, chat_id: str, session_id: str):
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT *
                FROM meeting_transcripts
                WHERE chat_id = ? AND session_id = ?
                """,
                (chat_id, session_id),
            )
            return cur.fetchone()

    def clear_transcript(self, chat_id: str, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM meeting_transcripts WHERE chat_id = ? AND session_id = ?",
                (chat_id, session_id),
            )
