"""Flask app for AI Wingman."""
from __future__ import annotations

import os
import secrets
from functools import wraps
from typing import Callable

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import db
from gemini import ask_gemini, build_persona_from_interview_prompt

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

db.init_db()


# ---------- Helpers ----------

def sanitize_text(value: str | None, max_len: int = 2000) -> str:
    """Strip control chars (keep \\n), trim, and cap length."""
    if not value:
        return ""
    cleaned = "".join(ch for ch in value if ch == "\n" or ord(ch) >= 32)
    return cleaned.strip()[:max_len]


def login_required(f: Callable) -> Callable:
    """Redirect to /login if no session, or return 401 JSON for /api/ routes."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "not logged in"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def current_user_id() -> int:
    """Return the current session's user id."""
    return int(session["user_id"])


def _require_persona(persona_id: int):
    """Return the persona row or None when not owned by current user."""
    return db.get_persona(persona_id, current_user_id())


# ---------- Pages ----------

@app.route("/")
def landing() -> str:
    """Public landing page."""
    return render_template("landing.html", logged_in="user_id" in session)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Create a new account, hash the password, start a session."""
    if request.method == "POST":
        username = sanitize_text(request.form.get("username"), 40).lower()
        password = request.form.get("password") or ""
        if len(username) < 3:
            flash("Username needs at least 3 chars. Try harder.")
            return render_template("register.html")
        if len(password) < 6:
            flash("Password needs at least 6 chars. Be serious.")
            return render_template("register.html")
        if db.get_user_by_username(username):
            flash("Username is taken. Someone got there first. Painful.")
            return render_template("register.html")
        user_id = db.create_user(username, generate_password_hash(password))
        session["user_id"] = user_id
        session["username"] = username
        return redirect(url_for("main_app"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Validate credentials and start a session."""
    if request.method == "POST":
        username = sanitize_text(request.form.get("username"), 40).lower()
        password = request.form.get("password") or ""
        user = db.get_user_by_username(username)
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Wrong username or password. Embarrassing.")
            return render_template("login.html")
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        return redirect(url_for("main_app"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    """Clear the session and bounce back to landing."""
    session.clear()
    return redirect(url_for("landing"))


@app.route("/app")
@login_required
def main_app() -> str:
    """Main app — persona list + suggestion UI."""
    return render_template("main.html", username=session.get("username"))


# ---------- Persona API ----------

@app.route("/api/personas")
@login_required
def api_list_personas():
    """Return the current user's personas as JSON."""
    rows = db.get_personas_for_user(current_user_id())
    return jsonify([
        {
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            "source": r["source"],
            "created_at": r["created_at"],
        }
        for r in rows
    ])


@app.route("/api/persona/<int:persona_id>")
@login_required
def api_get_persona(persona_id: int):
    """Return a single persona with its messages + latest vibe."""
    persona = _require_persona(persona_id)
    if persona is None:
        return jsonify({"error": "not found"}), 404
    msgs = db.get_messages(persona_id)
    vibe = db.get_latest_vibe(persona_id)
    return jsonify({
        "id": persona["id"],
        "name": persona["name"],
        "description": persona["description"],
        "source": persona["source"],
        "messages": [
            {
                "sender": m["sender"],
                "content": m["content"],
                "created_at": m["created_at"],
            }
            for m in msgs
        ],
        "vibe": {"score": vibe["score"], "note": vibe["note"]} if vibe else None,
    })


@app.route("/api/persona/<int:persona_id>", methods=["DELETE"])
@login_required
def api_delete_persona(persona_id: int):
    """Delete a persona and all of their messages + vibe history."""
    if _require_persona(persona_id) is None:
        return jsonify({"error": "not found"}), 404
    db.delete_persona(persona_id, current_user_id())
    return jsonify({"ok": True})


@app.route("/api/persona/interview", methods=["POST"])
@login_required
def api_persona_interview():
    """Create a persona from 5 interview answers; Gemini writes the description."""
    data = request.get_json(silent=True) or {}
    name = sanitize_text(data.get("name"), 60)
    if not name:
        return jsonify({"error": "name is required"}), 400
    answers = {
        "name": name,
        "where": sanitize_text(data.get("where"), 300),
        "vibe": sanitize_text(data.get("vibe"), 300),
        "stage": sanitize_text(data.get("stage"), 300),
        "extra": sanitize_text(data.get("extra"), 500),
    }
    description = ask_gemini(build_persona_from_interview_prompt(answers))
    persona_id = db.create_persona(
        current_user_id(), name, description, "conversation"
    )
    return jsonify({"id": persona_id, "name": name, "description": description})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
