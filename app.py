"""Flask app for AI Wingman — phase 1: skeleton + DB + landing."""
from __future__ import annotations

import os
import secrets

from dotenv import load_dotenv
from flask import Flask, render_template, session

import db

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

db.init_db()


@app.route("/")
def landing() -> str:
    """Public landing page."""
    return render_template("landing.html", logged_in="user_id" in session)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
