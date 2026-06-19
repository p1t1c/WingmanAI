# AGENTS.md — AI Wingman

Instructions for AI coding agents (and humans) contributing to this repo.

## Stack
- Backend: Python 3.11+ with Flask
- DB: SQLite via stdlib `sqlite3`, single file `wingman.db` (no ORM)
- AI: `google-genai` SDK, model `gemini-2.0-flash`
- Frontend: vanilla HTML/CSS/JS, mobile-first, served by Flask
- Auth: `werkzeug.security` password hashing + Flask sessions

## Hard rules
- Never commit `.env`, `wingman.db`, `venv/`, or `__pycache__/`.
- Every Gemini call wrapped in try/except → return a funny fallback, never a raw stack trace.
- Sanitize all user input before storing or sending to Gemini.
- Small functions with docstrings and type hints.
- Update `requirements.txt` after every new package.
- AI tone: funny, bold, slightly unhinged. No moralizing.

## Setup
```bash
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
copy .env.example .env           # then edit and put real keys
python app.py
```
Open http://localhost:5000.

## Layout
- `app.py` — Flask routes
- `db.py` — SQLite init + query helpers
- `gemini.py` — `ask_gemini()` + prompt builders
- `templates/` — Jinja templates
- `static/` — CSS + JS

## Build order
1. Skeleton + DB
2. Auth (register / login / session / logout)
3. Persona via conversational interview
4. Suggestions: vibe score + 3 replies (core demo)
5. Screenshot input (persona-from-profile + chat extraction)
6. Coaching tab + roast
7. Old chat analysis (pasted text)
8. Polish: hilarious landing, mobile tightening, spinners
