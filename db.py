"""SQLite database helpers for AI Wingman.

Single-file DB at ``wingman.db`` next to this module. No ORM — just stdlib
``sqlite3``. All functions open and close their own short-lived connection so
the app can stay simple across threads.

A ``conversations`` table groups messages into sessions per persona. Each
persona has at most one active conversation (``ended_at IS NULL``). Resetting
the chat ends the active one and starts a fresh one on the next message.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "wingman.db"


def get_db() -> sqlite3.Connection:
    """Return a connection with Row factory and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if ``table`` has a column named ``column``."""
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c["name"] == column for c in cols)


def init_db() -> None:
    """Create all tables, and migrate older DBs to add conversation grouping."""
    conn = get_db()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS personas (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                persona_id INTEGER NOT NULL,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (persona_id) REFERENCES personas(id)
            );

            CREATE TABLE IF NOT EXISTS vibe_scores (
                id INTEGER PRIMARY KEY,
                persona_id INTEGER NOT NULL,
                score INTEGER NOT NULL,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (persona_id) REFERENCES personas(id)
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY,
                persona_id INTEGER NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP,
                FOREIGN KEY (persona_id) REFERENCES personas(id)
            );
            """
        )

        # Migrate older DBs: add conversation_id columns where missing.
        if not _column_exists(conn, "messages", "conversation_id"):
            conn.execute("ALTER TABLE messages ADD COLUMN conversation_id INTEGER")
        if not _column_exists(conn, "vibe_scores", "conversation_id"):
            conn.execute("ALTER TABLE vibe_scores ADD COLUMN conversation_id INTEGER")

        # Backfill: for any persona with rows missing a conversation_id, create
        # a single conversation per persona and assign everything to it.
        orphan_personas = {
            r["persona_id"]
            for r in conn.execute(
                "SELECT DISTINCT persona_id FROM messages WHERE conversation_id IS NULL"
            ).fetchall()
        } | {
            r["persona_id"]
            for r in conn.execute(
                "SELECT DISTINCT persona_id FROM vibe_scores WHERE conversation_id IS NULL"
            ).fetchall()
        }
        for persona_id in orphan_personas:
            cur = conn.execute(
                "INSERT INTO conversations (persona_id) VALUES (?)", (persona_id,)
            )
            conv_id = int(cur.lastrowid)
            conn.execute(
                "UPDATE messages SET conversation_id = ? "
                "WHERE persona_id = ? AND conversation_id IS NULL",
                (conv_id, persona_id),
            )
            conn.execute(
                "UPDATE vibe_scores SET conversation_id = ? "
                "WHERE persona_id = ? AND conversation_id IS NULL",
                (conv_id, persona_id),
            )

        conn.commit()
    finally:
        conn.close()


def _active_conversation_id(conn: sqlite3.Connection, persona_id: int) -> int:
    """Return the active conversation id for the persona, creating one if needed."""
    row = conn.execute(
        "SELECT id FROM conversations WHERE persona_id = ? AND ended_at IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (persona_id,),
    ).fetchone()
    if row is not None:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO conversations (persona_id) VALUES (?)", (persona_id,)
    )
    return int(cur.lastrowid)


# ---------- User helpers ----------

def create_user(username: str, password_hash: str) -> int:
    """Insert a new user, return the new row id."""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def get_user_by_username(username: str) -> sqlite3.Row | None:
    """Fetch a user row by username, or None."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> sqlite3.Row | None:
    """Fetch a user row by id, or None."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()


# ---------- Persona helpers ----------

def create_persona(user_id: int, name: str, description: str, source: str) -> int:
    """Create a persona owned by ``user_id``; return new row id."""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO personas (user_id, name, description, source) "
            "VALUES (?, ?, ?, ?)",
            (user_id, name, description, source),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def get_personas_for_user(user_id: int) -> list[sqlite3.Row]:
    """All personas for a user, newest first."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM personas WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()


def get_persona(persona_id: int, user_id: int) -> sqlite3.Row | None:
    """Fetch a single persona owned by ``user_id``."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM personas WHERE id = ? AND user_id = ?",
            (persona_id, user_id),
        ).fetchone()
    finally:
        conn.close()


def delete_persona(persona_id: int, user_id: int) -> None:
    """Delete a persona and all of its messages, vibe scores, and conversations."""
    conn = get_db()
    try:
        owned = conn.execute(
            "SELECT id FROM personas WHERE id = ? AND user_id = ?",
            (persona_id, user_id),
        ).fetchone()
        if owned is None:
            return
        conn.execute("DELETE FROM vibe_scores WHERE persona_id = ?", (persona_id,))
        conn.execute("DELETE FROM messages WHERE persona_id = ?", (persona_id,))
        conn.execute("DELETE FROM conversations WHERE persona_id = ?", (persona_id,))
        conn.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
        conn.commit()
    finally:
        conn.close()


# ---------- Conversation helpers ----------

def reset_active_conversation(persona_id: int, user_id: int) -> int | None:
    """End the active conversation for a persona. Returns the closed conversation id.

    Returns None if the persona is not owned by ``user_id`` or has no active chat
    with at least one message in it (we don't bother archiving empty sessions).
    """
    conn = get_db()
    try:
        owned = conn.execute(
            "SELECT id FROM personas WHERE id = ? AND user_id = ?",
            (persona_id, user_id),
        ).fetchone()
        if owned is None:
            return None
        active = conn.execute(
            "SELECT id FROM conversations WHERE persona_id = ? AND ended_at IS NULL",
            (persona_id,),
        ).fetchone()
        if active is None:
            return None
        # Only archive if the active conversation actually has messages.
        has_msgs = conn.execute(
            "SELECT 1 FROM messages WHERE conversation_id = ? LIMIT 1",
            (active["id"],),
        ).fetchone()
        if has_msgs is None:
            return None
        conn.execute(
            "UPDATE conversations SET ended_at = CURRENT_TIMESTAMP WHERE id = ?",
            (active["id"],),
        )
        conn.commit()
        return int(active["id"])
    finally:
        conn.close()


def get_archives_for_user(user_id: int) -> list[dict]:
    """Return all ended conversations for the user, newest-first, with summary stats."""
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT
              c.id AS id,
              c.persona_id AS persona_id,
              c.started_at AS started_at,
              c.ended_at AS ended_at,
              p.name AS persona_name,
              (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS msg_count,
              (SELECT score FROM vibe_scores v WHERE v.conversation_id = c.id
                 ORDER BY v.created_at DESC, v.id DESC LIMIT 1) AS last_vibe,
              (SELECT note FROM vibe_scores v WHERE v.conversation_id = c.id
                 ORDER BY v.created_at DESC, v.id DESC LIMIT 1) AS last_vibe_note
            FROM conversations c
            JOIN personas p ON p.id = c.persona_id
            WHERE p.user_id = ? AND c.ended_at IS NOT NULL
            ORDER BY c.ended_at DESC, c.id DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_conversation(conversation_id: int, user_id: int) -> sqlite3.Row | None:
    """Fetch a conversation row, but only if it belongs to a persona of ``user_id``."""
    conn = get_db()
    try:
        return conn.execute(
            """
            SELECT c.*, p.name AS persona_name, p.description AS persona_description
            FROM conversations c
            JOIN personas p ON p.id = c.persona_id
            WHERE c.id = ? AND p.user_id = ?
            """,
            (conversation_id, user_id),
        ).fetchone()
    finally:
        conn.close()


def get_messages_for_conversation(conversation_id: int) -> list[sqlite3.Row]:
    """Return messages from a specific conversation in chronological order."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? "
            "ORDER BY created_at ASC, id ASC",
            (conversation_id,),
        ).fetchall()
        return list(rows)
    finally:
        conn.close()


def delete_conversation(conversation_id: int, user_id: int) -> bool:
    """Hard-delete an archived conversation owned by ``user_id``. Returns True on success."""
    conn = get_db()
    try:
        owned = conn.execute(
            """
            SELECT c.id FROM conversations c
            JOIN personas p ON p.id = c.persona_id
            WHERE c.id = ? AND p.user_id = ?
            """,
            (conversation_id, user_id),
        ).fetchone()
        if owned is None:
            return False
        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
        )
        conn.execute(
            "DELETE FROM vibe_scores WHERE conversation_id = ?", (conversation_id,)
        )
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        conn.commit()
        return True
    finally:
        conn.close()


# ---------- Message helpers ----------

def add_message(persona_id: int, sender: str, content: str) -> int:
    """Append a chat message to the persona's active conversation."""
    conn = get_db()
    try:
        conv_id = _active_conversation_id(conn, persona_id)
        cur = conn.execute(
            "INSERT INTO messages (persona_id, sender, content, conversation_id) "
            "VALUES (?, ?, ?, ?)",
            (persona_id, sender, content, conv_id),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def get_messages(persona_id: int, limit: int = 200) -> list[sqlite3.Row]:
    """Return messages from the persona's active conversation, chronological."""
    conn = get_db()
    try:
        active = conn.execute(
            "SELECT id FROM conversations WHERE persona_id = ? AND ended_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (persona_id,),
        ).fetchone()
        if active is None:
            return []
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? "
            "ORDER BY created_at ASC, id ASC LIMIT ?",
            (int(active["id"]), limit),
        ).fetchall()
        return list(rows)
    finally:
        conn.close()


# ---------- Vibe score helpers ----------

def add_vibe_score(persona_id: int, score: int, note: str) -> int:
    """Save a new vibe score row tied to the active conversation."""
    conn = get_db()
    try:
        conv_id = _active_conversation_id(conn, persona_id)
        cur = conn.execute(
            "INSERT INTO vibe_scores (persona_id, score, note, conversation_id) "
            "VALUES (?, ?, ?, ?)",
            (persona_id, score, note, conv_id),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def get_latest_vibe(persona_id: int) -> sqlite3.Row | None:
    """Most recent vibe score for the persona's active conversation."""
    conn = get_db()
    try:
        active = conn.execute(
            "SELECT id FROM conversations WHERE persona_id = ? AND ended_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (persona_id,),
        ).fetchone()
        if active is None:
            return None
        return conn.execute(
            "SELECT * FROM vibe_scores WHERE conversation_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (int(active["id"]),),
        ).fetchone()
    finally:
        conn.close()


def get_vibe_history(persona_id: int) -> list[sqlite3.Row]:
    """Vibe scores from the persona's active conversation in chronological order."""
    conn = get_db()
    try:
        active = conn.execute(
            "SELECT id FROM conversations WHERE persona_id = ? AND ended_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (persona_id,),
        ).fetchone()
        if active is None:
            return []
        return conn.execute(
            "SELECT * FROM vibe_scores WHERE conversation_id = ? "
            "ORDER BY created_at ASC, id ASC",
            (int(active["id"]),),
        ).fetchall()
    finally:
        conn.close()
