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
from gemini import (
    FALLBACK_REPLIES,
    ask_gemini,
    build_chat_extraction_prompt,
    build_coaching_prompt,
    build_old_chat_analysis_prompt,
    build_persona_from_image_prompt,
    build_persona_from_interview_prompt,
    build_suggestions_prompt,
    parse_json_or_fallback,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB upload cap

ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}

db.init_db()


# ---------- Helpers ----------

def sanitize_text(value: str | None, max_len: int = 2000) -> str:
    """Strip control chars (keep \\n), trim, and cap length."""
    if not value:
        return ""
    cleaned = "".join(ch for ch in value if ch == "\n" or ord(ch) >= 32)
    return cleaned.strip()[:max_len]


def login_required(f: Callable) -> Callable:
    """Redirect to /login if no session, or return 401 JSON for /api/ routes.

    Also validates that the session's user_id still points to a real user — if
    the DB was wiped or the user deleted, we kill the stale cookie instead of
    letting downstream queries fail on a foreign-key constraint.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        user_id = session.get("user_id")
        if user_id is not None and db.get_user_by_id(user_id) is None:
            session.clear()
            user_id = None
        if user_id is None:
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

@app.route('/sw.js')
def sw():
    """Serve the service worker from the root."""
    return app.send_static_file('sw.js')

@app.route('/.well-known/assetlinks.json')
def assetlinks():
    """Serve the Digital Asset Links verification file."""
    return app.send_static_file('assetlinks.json')

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


@app.route("/coaching")
@login_required
def coaching_page() -> str:
    """Coaching tab — stats + funny roast."""
    return render_template("coaching.html", username=session.get("username"))


@app.route("/archives")
@login_required
def archives_page() -> str:
    """Archives tab — list of past conversations, each individually analyzable."""
    return render_template("archives.html", username=session.get("username"))


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


@app.route("/api/persona/<int:persona_id>/messages", methods=["POST"])
@login_required
def api_add_messages(persona_id: int):
    """Append one or more typed messages to a persona's conversation."""
    if _require_persona(persona_id) is None:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or {}
    raw_msgs = data.get("messages") or []
    if not isinstance(raw_msgs, list):
        return jsonify({"error": "messages must be a list"}), 400
    saved = 0
    for m in raw_msgs:
        if not isinstance(m, dict):
            continue
        sender = m.get("sender")
        content = sanitize_text(m.get("content"), 2000)
        if sender in ("me", "them") and content:
            db.add_message(persona_id, sender, content)
            saved += 1
    return jsonify({"saved": saved})


@app.route("/api/persona/<int:persona_id>/suggest", methods=["POST"])
@login_required
def api_suggest(persona_id: int):
    """Generate a vibe score + 3 ranked replies. Persist the vibe score."""
    persona = _require_persona(persona_id)
    if persona is None:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or {}
    personality = sanitize_text(data.get("personality"), 30).lower() or "funny"
    custom_personality = sanitize_text(data.get("custom_personality"), 200)
    try:
        intensity = int(data.get("intensity", 70))
    except (TypeError, ValueError):
        intensity = 70
    intensity = max(0, min(100, intensity))

    msgs_rows = db.get_messages(persona_id)
    msgs = [{"sender": m["sender"], "content": m["content"]} for m in msgs_rows]
    prompt = build_suggestions_prompt(
        persona["description"] or "", msgs, personality, intensity, custom_personality
    )
    raw = ask_gemini(prompt, temperature=1.0)
    parsed = parse_json_or_fallback(raw, FALLBACK_REPLIES)

    try:
        score = int(parsed.get("vibe_score", 50))
    except (TypeError, ValueError):
        score = 50
    score = max(0, min(100, score))
    note = sanitize_text(str(parsed.get("vibe_note", "")), 200) or "Vibes inconclusive."
    db.add_vibe_score(persona_id, score, note)

    raw_replies = parsed.get("replies") if isinstance(parsed, dict) else None
    clean_replies: list[dict[str, str]] = []
    for r in (raw_replies or [])[:3]:
        if not isinstance(r, dict):
            continue
        label = sanitize_text(str(r.get("label", "")), 20).lower() or "safe"
        if label not in ("safe", "bold", "unhinged"):
            label = "safe"
        text = sanitize_text(str(r.get("text", "")), 600)
        if text:
            clean_replies.append({"label": label, "text": text})
    if not clean_replies:
        clean_replies = FALLBACK_REPLIES["replies"]

    return jsonify({
        "vibe_score": score,
        "vibe_note": note,
        "replies": clean_replies,
    })


@app.route("/api/persona/screenshot", methods=["POST"])
@login_required
def api_persona_screenshot():
    """Create a persona from a dating profile screenshot via Gemini Vision."""
    name = sanitize_text(request.form.get("name"), 60)
    if not name:
        return jsonify({"error": "name is required"}), 400
    file = request.files.get("image")
    if file is None or not file.filename:
        return jsonify({"error": "image is required"}), 400
    mime = (file.mimetype or "image/jpeg").lower()
    if mime not in ALLOWED_IMAGE_MIMES:
        return jsonify({"error": "image type not supported. use jpg/png/webp"}), 400
    img_bytes = file.read()
    if not img_bytes:
        return jsonify({"error": "image was empty"}), 400
    description = ask_gemini(
        build_persona_from_image_prompt(),
        image=img_bytes,
        image_mime=mime,
    )
    persona_id = db.create_persona(
        current_user_id(), name, description, "screenshot"
    )
    return jsonify({"id": persona_id, "name": name, "description": description})


@app.route("/api/persona/<int:persona_id>/screenshot", methods=["POST"])
@login_required
def api_chat_screenshot(persona_id: int):
    """Extract messages from a chat screenshot and save them under a persona."""
    if _require_persona(persona_id) is None:
        return jsonify({"error": "not found"}), 404
    file = request.files.get("image")
    if file is None or not file.filename:
        return jsonify({"error": "image is required"}), 400
    mime = (file.mimetype or "image/jpeg").lower()
    if mime not in ALLOWED_IMAGE_MIMES:
        return jsonify({"error": "image type not supported. use jpg/png/webp"}), 400
    img_bytes = file.read()
    if not img_bytes:
        return jsonify({"error": "image was empty"}), 400
    raw = ask_gemini(
        build_chat_extraction_prompt(),
        image=img_bytes,
        image_mime=mime,
        temperature=0.2,
    )
    parsed = parse_json_or_fallback(raw, [])
    items = parsed if isinstance(parsed, list) else parsed.get("items", [])
    saved = 0
    for m in items:
        if not isinstance(m, dict):
            continue
        sender = m.get("sender")
        content = sanitize_text(m.get("content"), 2000)
        if sender in ("me", "them") and content:
            db.add_message(persona_id, sender, content)
            saved += 1
    return jsonify({"saved": saved})


@app.route("/api/persona/<int:persona_id>/reset", methods=["POST"])
@login_required
def api_reset_conversation(persona_id: int):
    """End the persona's active conversation, archiving its messages + vibe scores."""
    if _require_persona(persona_id) is None:
        return jsonify({"error": "not found"}), 404
    archived_id = db.reset_active_conversation(persona_id, current_user_id())
    if archived_id is None:
        return jsonify({
            "ok": True,
            "archived_id": None,
            "note": "nothing to archive — chat was empty",
        })
    return jsonify({"ok": True, "archived_id": archived_id})


@app.route("/api/archives")
@login_required
def api_list_archives():
    """Return all archived (ended) conversations for the current user."""
    rows = db.get_archives_for_user(current_user_id())
    return jsonify(rows)


@app.route("/api/archives/<int:conv_id>")
@login_required
def api_get_archive(conv_id: int):
    """Return one archived conversation with its messages."""
    conv = db.get_conversation(conv_id, current_user_id())
    if conv is None:
        return jsonify({"error": "not found"}), 404
    msgs = db.get_messages_for_conversation(conv_id)
    return jsonify({
        "id": conv["id"],
        "persona_id": conv["persona_id"],
        "persona_name": conv["persona_name"],
        "persona_description": conv["persona_description"],
        "started_at": conv["started_at"],
        "ended_at": conv["ended_at"],
        "messages": [
            {
                "sender": m["sender"],
                "content": m["content"],
                "created_at": m["created_at"],
            }
            for m in msgs
        ],
    })


@app.route("/api/archives/<int:conv_id>", methods=["DELETE"])
@login_required
def api_delete_archive(conv_id: int):
    """Permanently delete an archived conversation."""
    if not db.delete_conversation(conv_id, current_user_id()):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/archives/<int:conv_id>/analyze", methods=["POST"])
@login_required
def api_analyze_archive(conv_id: int):
    """Run the same analyze pipeline used for pasted chats on an archived session."""
    conv = db.get_conversation(conv_id, current_user_id())
    if conv is None:
        return jsonify({"error": "not found"}), 404
    msgs = db.get_messages_for_conversation(conv_id)
    if not msgs:
        return jsonify({"error": "no messages in this archive"}), 400
    transcript_lines = []
    for m in msgs:
        who = "me" if m["sender"] == "me" else "them"
        transcript_lines.append(f"{who}: {m['content']}")
    transcript = "\n".join(transcript_lines)
    analysis = ask_gemini(build_old_chat_analysis_prompt(transcript))
    return jsonify({"analysis": analysis})


@app.route("/api/analyze", methods=["POST"])
@login_required
def api_analyze():
    """Analyze a raw pasted chat — funny breakdown + what went right/wrong."""
    data = request.get_json(silent=True) or {}
    raw = sanitize_text(data.get("text"), 8000)
    if len(raw) < 20:
        return jsonify({"error": "paste a bit more text — at least 20 chars"}), 400
    analysis = ask_gemini(build_old_chat_analysis_prompt(raw))
    return jsonify({"analysis": analysis})


@app.route("/api/coaching")
@login_required
def api_coaching():
    """Compute texting stats and ask Gemini for a funny diagnosis."""
    user_id = current_user_id()
    personas = db.get_personas_for_user(user_id)
    persona_stats: list[dict] = []
    total_messages = 0
    my_messages = 0
    their_messages = 0
    double_text_count = 0
    my_len_sum = 0
    my_len_count = 0

    for p in personas:
        msgs = db.get_messages(p["id"], limit=500)
        history = db.get_vibe_history(p["id"])
        latest_vibe = history[-1]["score"] if history else None
        first_vibe = history[0]["score"] if history else None
        trend = (
            int(latest_vibe) - int(first_vibe)
            if latest_vibe is not None and first_vibe is not None
            else 0
        )
        persona_stats.append({
            "name": p["name"],
            "messages_count": len(msgs),
            "latest_vibe": latest_vibe,
            "first_vibe": first_vibe,
            "trend": trend,
        })
        prev = None
        for m in msgs:
            total_messages += 1
            if m["sender"] == "me":
                my_messages += 1
                my_len_sum += len(m["content"] or "")
                my_len_count += 1
                if prev == "me":
                    double_text_count += 1
            else:
                their_messages += 1
            prev = m["sender"]

    avg_my_len = round(my_len_sum / my_len_count, 1) if my_len_count else 0
    double_text_rate = (
        round(100 * double_text_count / my_messages, 1) if my_messages else 0
    )
    stats = {
        "personas": persona_stats,
        "total_messages": total_messages,
        "my_messages": my_messages,
        "their_messages": their_messages,
        "double_text_rate_pct": double_text_rate,
        "avg_my_message_chars": avg_my_len,
    }
    if total_messages == 0:
        roast = (
            "No data, no roast. You haven't sent a single message inside the app. "
            "Either add some chats or admit you're scared. We're rooting for you."
        )
    else:
        roast = ask_gemini(build_coaching_prompt(stats))
    return jsonify({"stats": stats, "roast": roast})


# ---------- Error handlers ----------

@app.errorhandler(413)
def too_big(_e):
    """Funny message when the user yeets a 50 MB screenshot at us."""
    return jsonify({"error": "image too chunky. 8 MB max — try compressing."}), 413


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "not found"}), 404
    return ("Nothing here. Take an L and go back.", 404)


@app.errorhandler(500)
def server_error(_e):
    """Funny message instead of a 500 stack trace."""
    if request.path.startswith("/api/"):
        return jsonify({
            "error": "Wingman pulled a hamstring. Refresh and try again."
        }), 500
    return ("Server tripped over its own feet. Try again in a sec.", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
