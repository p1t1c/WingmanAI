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
    """Redirect to /login if no session, or 401 for API routes."""
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
    """Authed app shell (filled out in later phases)."""
    return render_template("main.html", username=session.get("username"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
