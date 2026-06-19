"""SQLite database helpers for AI Wingman.

Single-file DB at ``wingman.db`` next to this module. No ORM — just stdlib
``sqlite3``. All functions open and close their own short-lived connection so
the app can stay simple across threads.
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


def init_db() -> None:
    """Create all tables if they do not already exist."""
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
            """
        )
        conn.commit()
    finally:
        conn.close()


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
    """Delete a persona and its messages + vibe history."""
    conn = get_db()
    try:
        # Confirm ownership before nuking dependents.
        owned = conn.execute(
            "SELECT id FROM personas WHERE id = ? AND user_id = ?",
            (persona_id, user_id),
        ).fetchone()
        if owned is None:
            return
        conn.execute("DELETE FROM vibe_scores WHERE persona_id = ?", (persona_id,))
        conn.execute("DELETE FROM messages WHERE persona_id = ?", (persona_id,))
        conn.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
        conn.commit()
    finally:
        conn.close()


# ---------- Message helpers ----------

def add_message(persona_id: int, sender: str, content: str) -> int:
    """Append a chat message; return new row id."""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO messages (persona_id, sender, content) VALUES (?, ?, ?)",
            (persona_id, sender, content),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def get_messages(persona_id: int, limit: int = 200) -> list[sqlite3.Row]:
    """Return messages for a persona in chronological order, capped by ``limit``."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM messages WHERE persona_id = ? "
            "ORDER BY created_at ASC, id ASC LIMIT ?",
            (persona_id, limit),
        ).fetchall()
        return list(rows)
    finally:
        conn.close()


# ---------- Vibe score helpers ----------

def add_vibe_score(persona_id: int, score: int, note: str) -> int:
    """Save a new vibe score row; return its id."""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO vibe_scores (persona_id, score, note) VALUES (?, ?, ?)",
            (persona_id, score, note),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def get_latest_vibe(persona_id: int) -> sqlite3.Row | None:
    """Most recent vibe score for the persona, or None."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM vibe_scores WHERE persona_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (persona_id,),
        ).fetchone()
    finally:
        conn.close()


def get_vibe_history(persona_id: int) -> list[sqlite3.Row]:
    """Full vibe score history in chronological order."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM vibe_scores WHERE persona_id = ? "
            "ORDER BY created_at ASC, id ASC",
            (persona_id,),
        ).fetchall()
    finally:
        conn.close()
