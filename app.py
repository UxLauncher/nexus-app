"""
╔══════════════════════════════════════════════════════════════════╗
║                    NEXUS  –  Community Platform                   ║
║         Modern Design  |  Flask + SQLite  |  Render-Ready        ║
╠══════════════════════════════════════════════════════════════════╣
║  Start:    python app.py                                         ║
║  Pakete:   pip install flask werkzeug                            ║
╚══════════════════════════════════════════════════════════════════╝
"""

# ═══════════════════════════════════════════════════════════════════
#   KONFIGURATION
# ═══════════════════════════════════════════════════════════════════

HOST           = "0.0.0.0"
PORT           = 8000
DEBUG          = False

SITE_TITLE     = "Nexus"
SITE_TAGLINE   = "Your Community. Your Space."

ADMIN_PASSWORD = "admin123"          # ⚠ Bitte ändern!
SECRET_KEY     = "change-me-in-production-please"  # ⚠ Bitte ändern!

DB_PATH        = "nexus.db"

# E-Mail Konfiguration (optional – für Bestätigungs-Mails)
MAIL_ENABLED   = False               # True wenn du SMTP konfiguriert hast
MAIL_SERVER    = "smtp.gmail.com"
MAIL_PORT      = 587
MAIL_USER      = ""                  # deine@gmail.com
MAIL_PASS      = ""                  # App-Passwort
MAIL_FROM      = ""

SERVER_CREATE_COST = 10              # Tokens um einen Server zu erstellen

# ═══════════════════════════════════════════════════════════════════
#   IMPORTS
# ═══════════════════════════════════════════════════════════════════
import sqlite3, socket, secrets, smtplib
from datetime import datetime
from email.mime.text import MIMEText
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (
    Flask, request, render_template_string,
    redirect, url_for, session, g, jsonify
)

app = Flask(__name__)
app.secret_key = SECRET_KEY

# ═══════════════════════════════════════════════════════════════════
#   DATENBANK
# ═══════════════════════════════════════════════════════════════════
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

@app.teardown_appcontext
def close_db(e):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL UNIQUE,
            email         TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            ip            TEXT,
            tokens        INTEGER DEFAULT 0,
            is_muted      INTEGER DEFAULT 0,
            mute_reason   TEXT,
            avatar_color  TEXT    DEFAULT '#6366f1',
            created_at    TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bans (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ip         TEXT    NOT NULL,
            username   TEXT    NOT NULL,
            email      TEXT    NOT NULL,
            reason     TEXT,
            banned_at  TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS global_messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            username   TEXT    NOT NULL,
            content    TEXT    NOT NULL,
            created_at TEXT    NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS friends (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            friend_id   INTEGER NOT NULL,
            status      TEXT    DEFAULT 'pending',
            created_at  TEXT    NOT NULL,
            UNIQUE(user_id, friend_id)
        );
        CREATE TABLE IF NOT EXISTS direct_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id   INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            content     TEXT    NOT NULL,
            is_read     INTEGER DEFAULT 0,
            created_at  TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS servers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            description TEXT,
            owner_id    INTEGER NOT NULL,
            invite_code TEXT    UNIQUE NOT NULL,
            created_at  TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS server_members (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL,
            user_id   INTEGER NOT NULL,
            role      TEXT    DEFAULT 'member',
            joined_at TEXT    NOT NULL,
            UNIQUE(server_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS server_messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id  INTEGER NOT NULL,
            user_id    INTEGER NOT NULL,
            username   TEXT    NOT NULL,
            content    TEXT    NOT NULL,
            created_at TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tickets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            subject     TEXT    NOT NULL,
            status      TEXT    DEFAULT 'open',
            created_at  TEXT    NOT NULL,
            closed_at   TEXT
        );
        CREATE TABLE IF NOT EXISTS ticket_messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id  INTEGER NOT NULL,
            sender_id  INTEGER NOT NULL,
            sender_name TEXT   NOT NULL,
            is_admin   INTEGER DEFAULT 0,
            content    TEXT    NOT NULL,
            created_at TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS email_tokens (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            token      TEXT    NOT NULL UNIQUE,
            type       TEXT    NOT NULL,
            data       TEXT,
            created_at TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            actor      TEXT    NOT NULL,
            action     TEXT    NOT NULL,
            details    TEXT,
            created_at TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS custom_pages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT    NOT NULL,
            slug         TEXT    NOT NULL UNIQUE,
            icon         TEXT    DEFAULT '📄',
            content      TEXT    NOT NULL,
            show_sidebar INTEGER DEFAULT 1,
            created_at   TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS premium_users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL UNIQUE,
            granted_at TEXT    NOT NULL,
            granted_by TEXT    NOT NULL
        );
    """)
    try:
        db.execute("ALTER TABLE users ADD COLUMN avatar_data TEXT")
    except Exception:
        pass
    try:
        db.execute("ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0")
    except Exception:
        pass
    db.commit()
    db.close()

with app.app_context():
    init_db()

# ═══════════════════════════════════════════════════════════════════
#   HELFER
# ═══════════════════════════════════════════════════════════════════
def get_ip():
    xff = request.environ.get("HTTP_X_FORWARDED_FOR")
    return xff.split(",")[0].strip() if xff else request.remote_addr

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except Exception:
        return "127.0.0.1"

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def today():
    return datetime.now().strftime("%Y-%m-%d")

def audit(action, details=None, user_id=None, actor="System"):
    try:
        db = get_db()
        db.execute("INSERT INTO audit_log (user_id, actor, action, details, created_at) VALUES (?,?,?,?,?)",
                   (user_id, actor, action, details, now()))
        db.commit()
    except Exception:
        pass

def send_email(to, subject, body):
    if not MAIL_ENABLED:
        return False
    try:
        msg = MIMEText(body, "html")
        msg["Subject"] = subject
        msg["From"]    = MAIL_FROM
        msg["To"]      = to
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as s:
            s.starttls()
            s.login(MAIL_USER, MAIL_PASS)
            s.send_message(msg)
        return True
    except Exception:
        return False

def avatar_initials(username):
    return username[0].upper() if username else "?"

AVATAR_COLORS = ["#6366f1","#8b5cf6","#ec4899","#f59e0b","#10b981","#3b82f6","#ef4444","#14b8a6"]

# ═══════════════════════════════════════════════════════════════════
#   BAN-MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════
@app.before_request
def check_ban():
    p = request.path
    if p == "/banned" or p.startswith("/admin") or p.startswith("/static"):
        return
    ip  = get_ip()
    ban = get_db().execute("SELECT id FROM bans WHERE ip=? LIMIT 1", (ip,)).fetchone()
    if ban:
        return redirect("/banned")

# ═══════════════════════════════════════════════════════════════════
#   DEKORATOREN
# ═══════════════════════════════════════════════════════════════════
def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*a, **kw)
    return dec

def admin_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*a, **kw)
    return dec

# ═══════════════════════════════════════════════════════════════════
#   GEMEINSAMES CSS  – modernes Design mit mehr Farben
# ═══════════════════════════════════════════════════════════════════
BASE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');

:root {
  --bg:        #0f0f13;
  --surface:   #18181f;
  --surface2:  #1f1f29;
  --surface3:  #26263a;
  --border:    rgba(255,255,255,.08);
  --border2:   rgba(255,255,255,.14);

  --indigo:    #6366f1;
  --purple:    #8b5cf6;
  --pink:      #ec4899;
  --amber:     #f59e0b;
  --emerald:   #10b981;
  --blue:      #3b82f6;
  --red:       #ef4444;
  --teal:      #14b8a6;

  --text:      #f1f0ff;
  --text2:     #a09cb8;
  --text3:     #5e5a7a;

  --radius:    12px;
  --radius-sm: 8px;
  --radius-lg: 18px;

  --shadow:    0 8px 32px rgba(0,0,0,.45);
  --glow-i:    0 0 32px rgba(99,102,241,.25);
  --glow-p:    0 0 32px rgba(139,92,246,.25);

  --sidebar-w: 260px;
  --topbar-h:  60px;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }

body {
  font-family: 'Plus Jakarta Sans', sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}

/* Subtle grid background */
body::before {
  content: '';
  position: fixed; inset: 0;
  background-image:
    linear-gradient(rgba(99,102,241,.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(99,102,241,.025) 1px, transparent 1px);
  background-size: 40px 40px;
  pointer-events: none; z-index: 0;
}

/* ── Auth Cards ── */
.auth-page {
  min-height: 100vh;
  display: flex; align-items: center; justify-content: center;
  padding: 2rem;
  background: radial-gradient(ellipse 80% 60% at 50% -10%, rgba(99,102,241,.18), transparent),
              radial-gradient(ellipse 60% 40% at 80% 100%, rgba(139,92,246,.12), transparent);
}

.auth-card {
  background: var(--surface);
  border: 1px solid var(--border2);
  border-radius: 24px;
  padding: 3rem 3.2rem;
  width: 100%; max-width: 460px;
  box-shadow: var(--shadow), 0 0 0 1px rgba(99,102,241,.12);
  animation: slideUp .45s cubic-bezier(.16,1,.3,1) both;
  position: relative; overflow: hidden;
}

.auth-card::before {
  content: '';
  position: absolute; top: 0; left: 50%; transform: translateX(-50%);
  width: 60%; height: 1px;
  background: linear-gradient(90deg, transparent, var(--indigo), transparent);
}

.auth-logo {
  display: flex; align-items: center; gap: .6rem;
  margin-bottom: 2rem;
}

.auth-logo-icon {
  width: 38px; height: 38px;
  background: linear-gradient(135deg, var(--indigo), var(--purple));
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.1rem; box-shadow: var(--glow-i);
}

.auth-logo-text {
  font-size: 1.1rem; font-weight: 800;
  background: linear-gradient(135deg, var(--indigo), var(--purple));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  letter-spacing: -.01em;
}

.auth-title { font-size: 1.8rem; font-weight: 800; letter-spacing: -.02em; margin-bottom: .3rem; }
.auth-sub   { color: var(--text2); font-size: .95rem; margin-bottom: 2rem; }

.form-group { margin-bottom: 1.1rem; }
.form-label {
  display: block; font-size: .72rem; font-weight: 700;
  letter-spacing: .1em; text-transform: uppercase;
  color: var(--text2); margin-bottom: .45rem;
}

.form-input {
  width: 100%;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text);
  font-family: 'Plus Jakarta Sans', sans-serif;
  font-size: .97rem; font-weight: 500;
  padding: .85rem 1rem;
  outline: none; transition: all .2s;
}
.form-input::placeholder { color: var(--text3); }
.form-input:focus {
  border-color: var(--indigo);
  background: rgba(99,102,241,.06);
  box-shadow: 0 0 0 3px rgba(99,102,241,.15);
}

.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: .5rem;
  padding: .85rem 1.4rem;
  border: none; border-radius: var(--radius);
  font-family: 'Plus Jakarta Sans', sans-serif;
  font-size: .95rem; font-weight: 700;
  cursor: pointer; transition: all .2s;
  text-decoration: none; letter-spacing: .01em;
}

.btn-primary {
  width: 100%;
  background: linear-gradient(135deg, var(--indigo), var(--purple));
  color: #fff;
  box-shadow: 0 4px 16px rgba(99,102,241,.4);
}
.btn-primary:hover { box-shadow: 0 6px 28px rgba(99,102,241,.55); transform: translateY(-1px); }
.btn-primary:active { transform: none; }

.btn-secondary {
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text2);
}
.btn-secondary:hover { border-color: var(--border2); color: var(--text); }

.btn-danger  { background: rgba(239,68,68,.12); border: 1px solid rgba(239,68,68,.25); color: var(--red); }
.btn-danger:hover  { background: rgba(239,68,68,.22); }
.btn-success { background: rgba(16,185,129,.12); border: 1px solid rgba(16,185,129,.25); color: var(--emerald); }
.btn-success:hover { background: rgba(16,185,129,.22); }
.btn-amber   { background: rgba(245,158,11,.12); border: 1px solid rgba(245,158,11,.25); color: var(--amber); }
.btn-amber:hover   { background: rgba(245,158,11,.22); }
.btn-sm      { padding: .38rem .85rem; font-size: .82rem; border-radius: 7px; }
.btn-xs      { padding: .25rem .6rem;  font-size: .75rem; border-radius: 6px; }

.alert {
  padding: .85rem 1rem; border-radius: var(--radius);
  margin-bottom: 1.1rem; font-size: .9rem; font-weight: 600;
  display: flex; align-items: center; gap: .5rem;
}
.alert-error   { background: rgba(239,68,68,.1);   border: 1px solid rgba(239,68,68,.2);   color: var(--red); }
.alert-success { background: rgba(16,185,129,.1);  border: 1px solid rgba(16,185,129,.2);  color: var(--emerald); }
.alert-info    { background: rgba(99,102,241,.1);  border: 1px solid rgba(99,102,241,.2);  color: var(--indigo); }
.alert-warn    { background: rgba(245,158,11,.1);  border: 1px solid rgba(245,158,11,.2);  color: var(--amber); }

.link { color: var(--indigo); text-decoration: none; font-weight: 600; transition: color .2s; }
.link:hover { color: var(--purple); }

/* ── App Layout ── */
.app-layout {
  display: flex;
  min-height: 100vh;
}

/* ── Sidebar ── */
.sidebar {
  width: var(--sidebar-w);
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
  position: fixed; top: 0; left: 0; bottom: 0;
  z-index: 100; transition: transform .3s;
}

.sidebar-logo {
  padding: 1.2rem 1.4rem;
  display: flex; align-items: center; gap: .7rem;
  border-bottom: 1px solid var(--border);
}

.logo-icon {
  width: 36px; height: 36px;
  background: linear-gradient(135deg, var(--indigo), var(--purple));
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 1rem; flex-shrink: 0;
  box-shadow: var(--glow-i);
}

.logo-name { font-size: 1.1rem; font-weight: 800; letter-spacing: -.01em;
  background: linear-gradient(135deg, var(--text), var(--text2));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; }

.sidebar-section { padding: .8rem .8rem .3rem; }
.sidebar-label {
  font-size: .65rem; font-weight: 700; letter-spacing: .12em;
  text-transform: uppercase; color: var(--text3);
  padding: 0 .6rem; margin-bottom: .4rem; display: block;
}

.sidebar-item {
  display: flex; align-items: center; gap: .75rem;
  padding: .62rem .8rem; border-radius: var(--radius-sm);
  color: var(--text2); text-decoration: none;
  font-size: .92rem; font-weight: 500;
  transition: all .15s; margin-bottom: .1rem; cursor: pointer; border: none;
  background: none; width: 100%; text-align: left;
}
.sidebar-item:hover { background: rgba(255,255,255,.05); color: var(--text); }
.sidebar-item.active {
  background: rgba(99,102,241,.15); color: var(--indigo);
  font-weight: 600;
}
.sidebar-item .icon { font-size: 1.05rem; width: 20px; text-align: center; flex-shrink: 0; }
.sidebar-item .badge-count {
  margin-left: auto;
  background: var(--red); color: #fff;
  font-size: .65rem; font-weight: 700;
  padding: .1rem .4rem; border-radius: 99px; min-width: 18px; text-align: center;
}

.sidebar-user {
  margin-top: auto;
  padding: 1rem;
  border-top: 1px solid var(--border);
  display: flex; align-items: center; gap: .8rem;
}

.sidebar-servers {
  padding: .4rem .8rem;
  flex: 1; overflow-y: auto;
}
.server-item {
  display: flex; align-items: center; gap: .7rem;
  padding: .55rem .7rem; border-radius: var(--radius-sm);
  color: var(--text2); text-decoration: none;
  font-size: .88rem; font-weight: 500;
  transition: all .15s; margin-bottom: .1rem;
}
.server-item:hover { background: rgba(255,255,255,.05); color: var(--text); }

/* ── Main Content ── */
.main-content {
  margin-left: var(--sidebar-w);
  flex: 1;
  display: flex; flex-direction: column;
  min-height: 100vh;
}

.topbar {
  height: var(--topbar-h);
  background: rgba(15,15,19,.8);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 2rem;
  position: sticky; top: 0; z-index: 50;
}

.topbar-title { font-size: 1.05rem; font-weight: 700; }
.topbar-actions { display: flex; align-items: center; gap: .8rem; }

.page-body { padding: 2rem; flex: 1; }

/* ── Cards & Panels ── */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 1.6rem;
  margin-bottom: 1.2rem;
}

.card-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 1.2rem;
}
.card-title { font-size: 1rem; font-weight: 700; }
.card-sub   { font-size: .82rem; color: var(--text2); margin-top: .2rem; }

.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px,1fr)); gap: 1rem; margin-bottom: 1.5rem; }

.stat-card {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.2rem 1.4rem;
}
.stat-label { font-size: .7rem; color: var(--text3); text-transform: uppercase; letter-spacing: .1em; font-weight: 600; }
.stat-value { font-size: 2rem; font-weight: 800; margin-top: .25rem; letter-spacing: -.03em; }

/* ── Avatar ── */
.avatar {
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-weight: 800; flex-shrink: 0; font-size: .85rem;
  color: #fff;
}
.av-sm  { width: 30px; height: 30px; font-size: .75rem; }
.av-md  { width: 38px; height: 38px; font-size: .9rem; }
.av-lg  { width: 52px; height: 52px; font-size: 1.2rem; }
.av-xl  { width: 72px; height: 72px; font-size: 1.8rem; }

/* ── Chat ── */
.chat-layout {
  display: flex; height: calc(100vh - var(--topbar-h));
}
.chat-main  { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.chat-panel { width: 260px; border-left: 1px solid var(--border); background: var(--surface); overflow-y: auto; }

.messages-area {
  flex: 1; overflow-y: auto;
  padding: 1.2rem 1.4rem;
  display: flex; flex-direction: column; gap: .7rem;
}

.msg {
  display: flex; gap: .9rem; align-items: flex-start;
  animation: msgPop .2s ease both;
}
@keyframes msgPop { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:none; } }

.msg-bubble { flex: 1; }
.msg-header { display: flex; align-items: baseline; gap: .55rem; margin-bottom: .2rem; }
.msg-name   { font-size: .88rem; font-weight: 700; }
.msg-time   { font-size: .72rem; color: var(--text3); }
.msg-text   {
  font-size: .93rem; line-height: 1.5; color: var(--text2);
  background: var(--surface2); border: 1px solid var(--border);
  padding: .6rem .9rem; border-radius: 0 12px 12px 12px;
  display: inline-block; max-width: 100%;
}

.msg-self .msg-text {
  background: rgba(99,102,241,.15); border-color: rgba(99,102,241,.25); color: var(--text);
}

.chat-input-area {
  padding: 1rem 1.4rem;
  border-top: 1px solid var(--border);
  display: flex; gap: .8rem; align-items: flex-end;
  flex-direction: row;
}
.chat-input-area textarea { order: 1; }
.chat-input-area button   { order: 2; }

.chat-input {
  flex: 1;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 12px;
  color: var(--text);
  font-family: 'Plus Jakarta Sans', sans-serif;
  font-size: .93rem; padding: .75rem 1rem;
  outline: none; resize: none; transition: border .2s;
}
.chat-input:focus { border-color: var(--indigo); }

.muted-notice {
  text-align: center; padding: .85rem;
  color: var(--red); font-size: .88rem;
  background: rgba(239,68,68,.07); border-top: 1px solid rgba(239,68,68,.15);
}

/* ── Tables ── */
.table-wrap { overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; }
.data-table thead th {
  padding: .75rem 1rem;
  text-align: left; font-size: .68rem; letter-spacing: .12em;
  text-transform: uppercase; color: var(--text3); font-weight: 700;
  border-bottom: 1px solid var(--border);
}
.data-table tbody tr { border-bottom: 1px solid var(--border); transition: background .12s; }
.data-table tbody tr:last-child { border-bottom: none; }
.data-table tbody tr:hover { background: rgba(255,255,255,.02); }
.data-table td { padding: .85rem 1rem; font-size: .9rem; vertical-align: middle; }

/* ── Badges ── */
.badge {
  display: inline-flex; align-items: center;
  padding: .2rem .6rem; border-radius: 99px;
  font-size: .7rem; font-weight: 700; letter-spacing: .05em;
}
.badge-indigo  { background: rgba(99,102,241,.15);  color: var(--indigo);  border: 1px solid rgba(99,102,241,.25); }
.badge-green   { background: rgba(16,185,129,.15);  color: var(--emerald); border: 1px solid rgba(16,185,129,.25); }
.badge-red     { background: rgba(239,68,68,.15);   color: var(--red);     border: 1px solid rgba(239,68,68,.25); }
.badge-amber   { background: rgba(245,158,11,.15);  color: var(--amber);   border: 1px solid rgba(245,158,11,.25); }
.badge-purple  { background: rgba(139,92,246,.15);  color: var(--purple);  border: 1px solid rgba(139,92,246,.25); }
.badge-teal    { background: rgba(20,184,166,.15);  color: var(--teal);    border: 1px solid rgba(20,184,166,.25); }

/* ── Misc ── */
.mono { font-family: 'JetBrains Mono', monospace; }

.input-row { display: flex; gap: .6rem; align-items: center; }
.input-inline {
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: var(--radius-sm); color: var(--text);
  font-family: 'Plus Jakarta Sans', sans-serif;
  font-size: .88rem; padding: .42rem .75rem;
  outline: none; transition: border .2s;
}
.input-inline:focus { border-color: var(--indigo); }
.input-inline.w-sm { width: 140px; }

.action-form { display: inline; }

.divider { height: 1px; background: var(--border); margin: 1.2rem 0; }

.empty { text-align: center; padding: 3.5rem 2rem; color: var(--text3); }
.empty-icon { font-size: 2.5rem; margin-bottom: .8rem; }

/* ── Tickets ── */
.ticket-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 1rem 1.2rem;
  border-bottom: 1px solid var(--border);
  transition: background .12s;
}
.ticket-item:last-child { border-bottom: none; }
.ticket-item:hover { background: rgba(255,255,255,.02); }

/* ── Admin layout ── */
.admin-body { padding: 2rem; }
.admin-topbar {
  background: rgba(15,15,19,.95);
  border-bottom: 1px solid var(--border);
  padding: 0 2rem; height: var(--topbar-h);
  display: flex; align-items: center; justify-content: space-between;
  position: sticky; top: 0; z-index: 50;
  backdrop-filter: blur(12px);
}

.tab-bar { display: flex; gap: .4rem; margin-bottom: 1.8rem; flex-wrap: wrap; }
.tab {
  padding: .48rem 1.1rem; border-radius: 8px;
  font-size: .85rem; font-weight: 600; cursor: pointer;
  text-decoration: none; transition: all .15s;
  border: 1px solid var(--border); color: var(--text2);
}
.tab.active, .tab:hover { border-color: var(--indigo); color: var(--indigo); background: rgba(99,102,241,.1); }

/* ── Banned ── */
.banned-page {
  min-height: 100vh; display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 2rem; text-align: center;
  background: radial-gradient(ellipse 60% 50% at 50% 50%, rgba(239,68,68,.08), transparent);
}

/* ── Animations ── */
@keyframes slideUp {
  from { opacity:0; transform:translateY(24px); }
  to   { opacity:1; transform:none; }
}
@keyframes fadeIn {
  from { opacity:0; } to { opacity:1; }
}

/* ── Mobile ── */
@media(max-width:768px){
  .sidebar { transform: translateX(-100%); }
  .sidebar.open { transform: none; }
  .main-content { margin-left: 0; }
  .chat-panel { display: none; }
  .stat-grid { grid-template-columns: 1fr 1fr; }
  .page-body { padding: 1rem; }
}

/* ── Token icon ── */
.token-icon { display: inline; color: var(--amber); }

/* ── Profile page ── */
.profile-header {
  background: linear-gradient(135deg, rgba(99,102,241,.15), rgba(139,92,246,.1));
  border: 1px solid rgba(99,102,241,.2);
  border-radius: var(--radius-lg);
  padding: 2rem;
  display: flex; gap: 1.5rem; align-items: center;
  margin-bottom: 1.5rem;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--surface3); border-radius: 3px; }

/* ── Reason input in admin tables ── */
.reason-input {
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 6px; color: var(--text);
  font-family: 'Plus Jakarta Sans', sans-serif;
  font-size: .82rem; padding: .32rem .65rem;
  width: 120px; outline: none; margin-right: .3rem;
}
</style>
"""

# ═══════════════════════════════════════════════════════════════════
#   SIDEBAR HELPER
# ═══════════════════════════════════════════════════════════════════
def get_sidebar_data(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    servers = db.execute("""
        SELECT s.* FROM servers s
        JOIN server_members sm ON sm.server_id=s.id
        WHERE sm.user_id=?
        ORDER BY s.name
    """, (user_id,)).fetchall()
    unread_dms = db.execute("""
        SELECT COUNT(*) as c FROM direct_messages
        WHERE receiver_id=? AND is_read=0
    """, (user_id,)).fetchone()["c"]
    pending_fr = db.execute("""
        SELECT COUNT(*) as c FROM friends
        WHERE friend_id=? AND status='pending'
    """, (user_id,)).fetchone()["c"]
    open_tickets = db.execute(
        "SELECT COUNT(*) as c FROM tickets WHERE user_id=? AND status='open'", (user_id,)).fetchone()["c"]
    return dict(user=user, servers=servers, unread_dms=unread_dms, pending_fr=pending_fr, open_tickets=open_tickets)

def render_avatar(user, size_class="av-sm"):
    col  = user["avatar_color"] or "#6366f1"
    init = avatar_initials(user["username"])
    try:
        if user["avatar_data"]:
            return f'<img src="{user["avatar_data"]}" class="avatar {size_class}" style="object-fit:cover">'
    except Exception:
        pass
    return f'<div class="avatar {size_class}" style="background:{col}">{init}</div>'

def render_sidebar(active="", user_id=None, extra_servers=None):
    if user_id is None:
        user_id = session.get("user_id")
    sd = get_sidebar_data(user_id)
    user    = sd["user"]
    servers = sd["servers"]
    try:
        is_premium = user["is_premium"]
    except Exception:
        is_premium = 0

    items = [
        ("🏠", "Dashboard",    url_for("dashboard"),    "dashboard",  0),
        ("💬", "Global Chat",  url_for("global_chat"),  "chat",       0),
        ("👥", "Friends",      url_for("friends"),       "friends",    sd["pending_fr"]),
        ("📨", "Messages",     url_for("dms"),           "dms",        sd["unread_dms"]),
        ("🖥️", "Servers",      url_for("servers_page"),  "servers",    0),
        ("🎫", "Support",      url_for("tickets"),       "tickets",    sd["open_tickets"]),
        ("👤", "Profile",      url_for("profile"),       "profile",    0),
    ]

    html = f"""
    <aside class="sidebar" id="sidebar">
      <div class="sidebar-logo">
        <div class="logo-icon">✦</div>
        <div class="logo-name">{SITE_TITLE}</div>
      </div>
      <div class="sidebar-section">
        <span class="sidebar-label">Navigation</span>
    """
    for icon, label, href, key, cnt in items:
        cls = "active" if active == key else ""
        badge = f'<span class="badge-count">{cnt}</span>' if cnt > 0 else ""
        html += f'<a href="{href}" class="sidebar-item {cls}"><span class="icon">{icon}</span>{label}{badge}</a>'

    try:
        db = get_db()
        custom_pages = db.execute("SELECT * FROM custom_pages WHERE show_sidebar=1 ORDER BY id ASC").fetchall()
        if custom_pages:
            html += '<div class="divider" style="margin:.6rem 0"></div><span class="sidebar-label">Pages</span>'
            for p in custom_pages:
                cls = "active" if active == f"page_{p['slug']}" else ""
                html += f'<a href="/page/{p["slug"]}" class="sidebar-item {cls}"><span class="icon">{p["icon"]}</span>{p["title"]}</a>'
    except Exception:
        pass

    if servers:
        html += '<div class="divider" style="margin:.6rem 0"></div><span class="sidebar-label">Your Servers</span>'
        for s in servers:
            html += f'<a href="{url_for("server_view", server_id=s["id"])}" class="sidebar-item"><span class="icon">🖥️</span>{s["name"]}</a>'

    pro_badge = '<span style="font-size:.6rem;background:linear-gradient(135deg,#f59e0b,#ec4899);color:#fff;padding:.1rem .4rem;border-radius:99px;font-weight:800;margin-left:.3rem">✦ PRO</span>' if is_premium else ""

    html += f"""
      </div>
      <div class="sidebar-user">
        {render_avatar(user, "av-sm")}
        <div style="flex:1;min-width:0">
          <div style="font-size:.85rem;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{user["username"]}{pro_badge}</div>
          <div style="font-size:.7rem;color:var(--text3)">{user["tokens"]} <span class="token-icon">⬡</span> tokens</div>
        </div>
        <a href="{url_for("logout")}" title="Logout" style="color:var(--text3);font-size:1.1rem;text-decoration:none">↩</a>
      </div>
    </aside>
    """
    return html

# ═══════════════════════════════════════════════════════════════════
#   TEMPLATES – AUTH
# ═══════════════════════════════════════════════════════════════════

AUTH_BASE = lambda title, body: f"""<!DOCTYPE html>
<html lang="de"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — {SITE_TITLE}</title>
{BASE_CSS}
</head><body>
<div class="auth-page">
  <div class="auth-card">
    <div class="auth-logo">
      <div class="auth-logo-icon">✦</div>
      <div class="auth-logo-text">{SITE_TITLE}</div>
    </div>
    {body}
  </div>
</div>
</body></html>"""

APP_BASE = lambda title, active, user_id, content: f"""<!DOCTYPE html>
<html lang="de"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — {SITE_TITLE}</title>
{BASE_CSS}
</head><body>
<div class="app-layout">
  {render_sidebar(active, user_id)}
  <div class="main-content">
    <div class="topbar">
      <button onclick="document.getElementById('sidebar').classList.toggle('open')"
              style="background:none;border:none;color:var(--text2);font-size:1.3rem;cursor:pointer;display:none" id="menu-btn">☰</button>
      <div class="topbar-title">{title}</div>
      <div class="topbar-actions">
        <span style="font-size:.85rem;color:var(--text3)" id="clock"></span>
      </div>
    </div>
    <div class="page-body">
      {content}
    </div>
  </div>
</div>
<script>
  function tick(){{const n=new Date();document.getElementById('clock').textContent=n.toLocaleTimeString('de-DE');}} tick(); setInterval(tick,1000);
  if(window.innerWidth<=768) document.getElementById('menu-btn').style.display='block';
</script>
</body></html>"""

# ═══════════════════════════════════════════════════════════════════
#   ROUTEN – AUTH
# ═══════════════════════════════════════════════════════════════════
@app.route("/")
def index():
    return redirect(url_for("dashboard") if session.get("user_id") else url_for("login"))

@app.route("/register", methods=["GET","POST"])
def register():
    form = {"username":"","email":""}
    error = None
    if request.method == "POST":
        username  = request.form.get("username","").strip()
        email     = request.form.get("email","").strip().lower()
        password  = request.form.get("password","")
        password2 = request.form.get("password2","")
        form = {"username":username,"email":email}
        if not username or not email or not password:
            error = "All fields are required."
        elif len(username) < 3:
            error = "Username must be at least 3 characters."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != password2:
            error = "Passwords do not match."
        elif "@" not in email:
            error = "Please enter a valid email address."
        else:
            db = get_db()
            if db.execute("SELECT id FROM users WHERE username=? OR email=?",(username,email)).fetchone():
                error = "Username or email already taken."
            else:
                color = AVATAR_COLORS[hash(username) % len(AVATAR_COLORS)]
                db.execute(
                    "INSERT INTO users (username,email,password_hash,ip,tokens,avatar_color,created_at) VALUES (?,?,?,?,?,?,?)",
                    (username,email,generate_password_hash(password),get_ip(),50,color,now())
                )
                db.commit()
                audit("register", f"New user registered: {username}", actor=username)
                session["reg_success"] = f"Account '{username}' created! You received 50 starter tokens. Login now."
                return redirect(url_for("login"))

    body = f"""
    <h2 class="auth-title">Create Account</h2>
    <p class="auth-sub">Join {SITE_TITLE} and get 50 starter tokens.</p>
    {'<div class="alert alert-error">⚠ '+error+'</div>' if error else ''}
    <form method="POST">
      <div class="form-group">
        <label class="form-label">Username</label>
        <input class="form-input" type="text" name="username" value="{form['username']}" placeholder="your_name" required autocomplete="off">
      </div>
      <div class="form-group">
        <label class="form-label">Email</label>
        <input class="form-input" type="email" name="email" value="{form['email']}" placeholder="mail@example.com" required>
      </div>
      <div class="form-group">
        <label class="form-label">Password</label>
        <input class="form-input" type="password" name="password" placeholder="Min. 6 characters" required>
      </div>
      <div class="form-group">
        <label class="form-label">Confirm Password</label>
        <input class="form-input" type="password" name="password2" placeholder="••••••••" required>
      </div>
      <button type="submit" class="btn btn-primary">Create Account</button>
    </form>
    <div style="text-align:center;margin-top:1.2rem;font-size:.9rem;color:var(--text2)">
      Already have an account? <a href="/login" class="link">Login →</a>
    </div>"""
    return AUTH_BASE("Register", body)

@app.route("/login", methods=["GET","POST"])
def login():
    form = {"identifier":""}
    error = None
    success = session.pop("reg_success", None)
    if request.method == "POST":
        identifier = request.form.get("identifier","").strip()
        password   = request.form.get("password","")
        form = {"identifier": identifier}
        if not identifier or not password:
            error = "Please fill in all fields."
        else:
            db   = get_db()
            user = db.execute(
                "SELECT * FROM users WHERE username=? OR email=?",
                (identifier, identifier.lower())
            ).fetchone()
            if not user or not check_password_hash(user["password_hash"], password):
                error = "Invalid credentials."
            else:
                session["user_id"]  = user["id"]
                session["username"] = user["username"]
                return redirect(url_for("dashboard"))

    body = f"""
    <h2 class="auth-title">Welcome back</h2>
    <p class="auth-sub">Sign in to your account.</p>
    {'<div class="alert alert-success">✓ '+success+'</div>' if success else ''}
    {'<div class="alert alert-error">⚠ '+error+'</div>' if error else ''}
    <form method="POST">
      <div class="form-group">
        <label class="form-label">Username or Email</label>
        <input class="form-input" type="text" name="identifier" value="{form['identifier']}" placeholder="name or mail@..." required autocomplete="off">
      </div>
      <div class="form-group">
        <label class="form-label">Password</label>
        <input class="form-input" type="password" name="password" placeholder="••••••••" required>
      </div>
      <button type="submit" class="btn btn-primary">Sign In</button>
    </form>
    <div style="text-align:center;margin-top:1.2rem;font-size:.9rem;color:var(--text2)">
      No account? <a href="/register" class="link">Register →</a>
    </div>"""
    return AUTH_BASE("Login", body)

@app.route("/logout")
def logout():
    session.pop("user_id",None); session.pop("username",None)
    return redirect(url_for("login"))

# ═══════════════════════════════════════════════════════════════════
#   DASHBOARD
# ═══════════════════════════════════════════════════════════════════
@app.route("/dashboard")
@login_required
def dashboard():
    uid = session["user_id"]
    db  = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if not user:
        return redirect(url_for("logout"))
    sd = get_sidebar_data(uid)
    col = user["avatar_color"] or "#6366f1"
    init = avatar_initials(user["username"])

    recent_msgs = db.execute(
        "SELECT * FROM global_messages ORDER BY id DESC LIMIT 5"
    ).fetchall()
    my_servers = len(sd["servers"])
    friends_c  = db.execute(
        "SELECT COUNT(*) as c FROM friends WHERE (user_id=? OR friend_id=?) AND status='accepted'",(uid,uid)).fetchone()["c"]

    content = f"""
    <div class="profile-header">
      <div class="avatar av-xl" style="background:{col}">{init}</div>
      <div>
        <div style="font-size:1.8rem;font-weight:800;letter-spacing:-.02em">{user['username']}</div>
        <div style="color:var(--text2);margin-top:.2rem">{user['email']}</div>
        <div style="margin-top:.6rem;display:flex;gap:.6rem;flex-wrap:wrap">
          <span class="badge badge-amber">⬡ {user['tokens']} Tokens</span>
          {'<span class="badge badge-red">🔇 Muted</span>' if user['is_muted'] else '<span class="badge badge-green">● Active</span>'}
          <span class="badge badge-indigo">Member since {user['created_at'][:10]}</span>
        </div>
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">Tokens</div>
        <div class="stat-value" style="color:var(--amber)">{user['tokens']}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Friends</div>
        <div class="stat-value" style="color:var(--emerald)">{friends_c}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Servers</div>
        <div class="stat-value" style="color:var(--indigo)">{my_servers}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Unread DMs</div>
        <div class="stat-value" style="color:var(--pink)">{sd['unread_dms']}</div>
      </div>
    </div>

    <div class="card">
      <div class="card-header"><div class="card-title">💬 Recent Global Chat</div>
        <a href="{url_for('global_chat')}" class="btn btn-secondary btn-sm">Open Chat →</a></div>
      {''.join([f"""<div style="display:flex;gap:.7rem;align-items:flex-start;margin-bottom:.75rem">
        <div class="avatar av-sm" style="background:#6366f1">{avatar_initials(m['username'])}</div>
        <div><div style="font-size:.83rem;font-weight:700">{m['username']}</div>
        <div style="font-size:.88rem;color:var(--text2)">{m['content'][:80]}</div></div></div>"""
        for m in recent_msgs]) if recent_msgs else '<div class="empty"><div class="empty-icon">💬</div>No messages yet</div>'}
    </div>
    """
    return APP_BASE("Dashboard", "dashboard", uid, content)

# ═══════════════════════════════════════════════════════════════════
#   GLOBAL CHAT
# ═══════════════════════════════════════════════════════════════════
@app.route("/chat")
@login_required
def global_chat():
    uid  = session["user_id"]
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    msgs = db.execute(
        "SELECT gm.*, u.avatar_color FROM global_messages gm JOIN users u ON u.id=gm.user_id ORDER BY gm.id DESC LIMIT 80"
    ).fetchall()
    msgs = list(reversed(msgs))

    msgs_html = ""
    for m in msgs:
        col  = m["avatar_color"] or "#6366f1"
        init = avatar_initials(m["username"])
        is_self = m["user_id"] == uid
        cls  = "msg-self" if is_self else ""
        msgs_html += f"""<div class="msg {cls}">
          <div class="avatar av-sm" style="background:{col}">{init}</div>
          <div class="msg-bubble">
            <div class="msg-header">
              <span class="msg-name" style="color:{col}">{m['username']}</span>
              <span class="msg-time">{m['created_at'][11:16]}</span>
            </div>
            <div class="msg-text">{m['content']}</div>
          </div>
        </div>"""

    if user["is_muted"]:
        input_html = f'<div class="muted-notice">🔇 You are muted{" — " + user["mute_reason"] if user["mute_reason"] else ""}. You cannot send messages.</div>'
    else:
        input_html = f"""
        <form class="chat-input-area" method="POST" action="{url_for('global_chat_post')}">
          <textarea class="chat-input" name="content" rows="1" placeholder="Message #global ..." required
            onkeydown="if(event.key==='Enter'&&!event.shiftKey){{event.preventDefault();this.form.submit()}}"></textarea>
          <button type="submit" class="btn btn-primary btn-sm">Send</button>
        </form>"""

    content = f"""
    <style>
      .page-body {{ padding: 0 !important; }}
    </style>
    <div class="chat-layout">
      <div class="chat-main">
        <div class="messages-area" id="msgs">{msgs_html}</div>
        {input_html}
      </div>
    </div>
    <script>
      const el = document.getElementById('msgs');
      el.scrollTop = el.scrollHeight;
    </script>"""
    return APP_BASE("Global Chat", "chat", uid, content)

@app.route("/chat/post", methods=["POST"])
@login_required
def global_chat_post():
    uid  = session["user_id"]
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if user["is_muted"]:
        return redirect(url_for("global_chat"))
    content = request.form.get("content","").strip()
    if content and len(content) <= 2000:
        db.execute(
            "INSERT INTO global_messages (user_id,username,content,created_at) VALUES (?,?,?,?)",
            (uid, user["username"], content, now())
        )
        db.commit()
    return redirect(url_for("global_chat"))

# ═══════════════════════════════════════════════════════════════════
#   FRIENDS
# ═══════════════════════════════════════════════════════════════════
@app.route("/friends")
@login_required
def friends():
    uid = session["user_id"]
    db  = get_db()
    accepted = db.execute("""
        SELECT u.* FROM friends f
        JOIN users u ON (u.id = CASE WHEN f.user_id=? THEN f.friend_id ELSE f.user_id END)
        WHERE (f.user_id=? OR f.friend_id=?) AND f.status='accepted'
    """,(uid,uid,uid)).fetchall()
    pending_in = db.execute("""
        SELECT f.id, u.username, u.avatar_color FROM friends f
        JOIN users u ON u.id=f.user_id
        WHERE f.friend_id=? AND f.status='pending'
    """,(uid,)).fetchall()
    pending_out = db.execute("""
        SELECT f.id, u.username FROM friends f
        JOIN users u ON u.id=f.friend_id
        WHERE f.user_id=? AND f.status='pending'
    """,(uid,)).fetchall()
    msg = session.pop("fr_msg",None)

    friends_html = ""
    for u in accepted:
        col  = u["avatar_color"] or "#6366f1"
        init = avatar_initials(u["username"])
        friends_html += f"""<div style="display:flex;align-items:center;gap:.9rem;padding:.85rem 0;border-bottom:1px solid var(--border)">
          <div class="avatar av-md" style="background:{col}">{init}</div>
          <div style="flex:1">
            <div style="font-weight:700">{u['username']}</div>
            <div class="badge badge-green" style="margin-top:.2rem">● Friend</div>
          </div>
          <a href="{url_for('dm_user', username=u['username'])}" class="btn btn-secondary btn-sm">💬 Message</a>
          <form class="action-form" method="POST" action="{url_for('friend_remove', friend_id=u['id'])}">
            <button type="submit" class="btn btn-danger btn-sm">Remove</button>
          </form>
        </div>"""

    incoming_html = ""
    for f in pending_in:
        col  = f["avatar_color"] or "#6366f1"
        init = avatar_initials(f["username"])
        incoming_html += f"""<div style="display:flex;align-items:center;gap:.9rem;padding:.75rem 0;border-bottom:1px solid var(--border)">
          <div class="avatar av-sm" style="background:{col}">{init}</div>
          <div style="flex:1;font-weight:600">{f['username']}</div>
          <form class="action-form" method="POST" action="{url_for('friend_accept', request_id=f['id'])}">
            <button type="submit" class="btn btn-success btn-xs">✓ Accept</button>
          </form>
          <form class="action-form" method="POST" action="{url_for('friend_decline', request_id=f['id'])}">
            <button type="submit" class="btn btn-danger btn-xs">✗ Decline</button>
          </form>
        </div>"""

    outgoing_html = ""
    for f in pending_out:
        outgoing_html += f"""<div style="display:flex;align-items:center;gap:.9rem;padding:.65rem 0;border-bottom:1px solid var(--border)">
          <div style="flex:1;color:var(--text2)">{f['username']}</div>
          <span class="badge badge-amber">Pending</span>
        </div>"""

    content = f"""
    {'<div class="alert alert-success">'+msg+'</div>' if msg else ''}

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.2rem;margin-bottom:1.2rem">
      <div class="card">
        <div class="card-title" style="margin-bottom:1rem">➕ Add Friend</div>
        <form method="POST" action="{url_for('friend_add')}">
          <div style="display:flex;gap:.6rem">
            <input class="form-input" type="text" name="username" placeholder="Username" required style="margin:0">
            <button type="submit" class="btn btn-primary btn-sm" style="white-space:nowrap">Send Request</button>
          </div>
        </form>
      </div>
      <div class="card">
        <div class="card-title" style="margin-bottom:.8rem">📬 Incoming Requests ({len(pending_in)})</div>
        {incoming_html if incoming_html else '<div style="color:var(--text3);font-size:.88rem">No pending requests</div>'}
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <div class="card-title">👥 Friends ({len(accepted)})</div>
      </div>
      {friends_html if friends_html else '<div class="empty"><div class="empty-icon">👥</div>No friends yet — add some!</div>'}
    </div>

    {'''<div class="card"><div class="card-title" style="margin-bottom:.8rem">⏳ Sent Requests</div>'''+outgoing_html+'''</div>''' if pending_out else ''}
    """
    return APP_BASE("Friends", "friends", uid, content)

@app.route("/friends/add", methods=["POST"])
@login_required
def friend_add():
    uid      = session["user_id"]
    uname    = session["username"]
    target_n = request.form.get("username","").strip()
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?",(target_n,)).fetchone()
    if not target or target["id"] == uid:
        session["fr_msg"] = "User not found or invalid."
    elif db.execute("SELECT id FROM friends WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)",
                    (uid,target["id"],target["id"],uid)).fetchone():
        session["fr_msg"] = "Friend request already exists or you're already friends."
    else:
        db.execute("INSERT INTO friends (user_id,friend_id,status,created_at) VALUES (?,?,'pending',?)",
                   (uid,target["id"],now()))
        db.commit()
        session["fr_msg"] = f"Friend request sent to {target_n}!"
    return redirect(url_for("friends"))

@app.route("/friends/accept/<int:request_id>", methods=["POST"])
@login_required
def friend_accept(request_id):
    db = get_db()
    db.execute("UPDATE friends SET status='accepted' WHERE id=? AND friend_id=?",(request_id, session["user_id"]))
    db.commit()
    return redirect(url_for("friends"))

@app.route("/friends/decline/<int:request_id>", methods=["POST"])
@login_required
def friend_decline(request_id):
    db = get_db()
    db.execute("DELETE FROM friends WHERE id=? AND friend_id=?",(request_id, session["user_id"]))
    db.commit()
    return redirect(url_for("friends"))

@app.route("/friends/remove/<int:friend_id>", methods=["POST"])
@login_required
def friend_remove(friend_id):
    uid = session["user_id"]
    db = get_db()
    db.execute("DELETE FROM friends WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)",
               (uid,friend_id,friend_id,uid))
    db.commit()
    return redirect(url_for("friends"))

# ═══════════════════════════════════════════════════════════════════
#   DIRECT MESSAGES
# ═══════════════════════════════════════════════════════════════════
@app.route("/dms")
@login_required
def dms():
    uid = session["user_id"]
    db  = get_db()
    # conversations: all users who have DMd or been DMd
    convs = db.execute("""
        SELECT DISTINCT CASE WHEN sender_id=? THEN receiver_id ELSE sender_id END as partner_id
        FROM direct_messages
        WHERE sender_id=? OR receiver_id=?
    """,(uid,uid,uid)).fetchall()

    convs_html = ""
    for c in convs:
        pid = c["partner_id"]
        partner = db.execute("SELECT * FROM users WHERE id=?",(pid,)).fetchone()
        if not partner: continue
        last_msg = db.execute("""
            SELECT * FROM direct_messages
            WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
            ORDER BY id DESC LIMIT 1
        """,(uid,pid,pid,uid)).fetchone()
        unread = db.execute("""
            SELECT COUNT(*) as c FROM direct_messages
            WHERE sender_id=? AND receiver_id=? AND is_read=0
        """,(pid,uid)).fetchone()["c"]
        col  = partner["avatar_color"] or "#6366f1"
        init = avatar_initials(partner["username"])
        convs_html += f"""<a href="{url_for('dm_user', username=partner['username'])}"
          style="display:flex;align-items:center;gap:.9rem;padding:.9rem 1.2rem;
                 border-bottom:1px solid var(--border);text-decoration:none;
                 transition:background .12s" onmouseover="this.style.background='rgba(255,255,255,.03)'" onmouseout="this.style.background=''">
          <div class="avatar av-md" style="background:{col}">{init}</div>
          <div style="flex:1;min-width:0">
            <div style="font-weight:700;font-size:.92rem">{partner['username']}</div>
            <div style="font-size:.82rem;color:var(--text3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
              {last_msg['content'][:40] if last_msg else 'No messages yet'}
            </div>
          </div>
          {'<span class="badge badge-indigo">'+str(unread)+'</span>' if unread else ''}
        </a>"""

    content = f"""
    <div class="card" style="padding:0;overflow:hidden">
      <div style="padding:1.2rem 1.4rem;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
        <div class="card-title">📨 Direct Messages</div>
      </div>
      {convs_html if convs_html else '<div class="empty"><div class="empty-icon">📨</div>No conversations yet.<br>Go to Friends and message someone!</div>'}
    </div>

    <div class="card">
      <div class="card-title" style="margin-bottom:1rem">💬 Start a Conversation</div>
      <form method="GET" action="{url_for('dms')}">
        <div style="display:flex;gap:.6rem">
          <input class="form-input" type="text" name="start_with" placeholder="Username" style="margin:0">
          <button type="submit" class="btn btn-primary btn-sm">Open DM</button>
        </div>
      </form>
    </div>"""

    start_with = request.args.get("start_with","").strip()
    if start_with:
        return redirect(url_for("dm_user", username=start_with))

    return APP_BASE("Direct Messages", "dms", uid, content)

@app.route("/dm/<username>", methods=["GET","POST"])
@login_required
def dm_user(username):
    uid = session["user_id"]
    db  = get_db()
    me  = db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    partner = db.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
    if not partner:
        return redirect(url_for("dms"))

    if request.method == "POST":
        if not me["is_muted"]:
            content = request.form.get("content","").strip()
            if content:
                db.execute(
                    "INSERT INTO direct_messages (sender_id,receiver_id,content,created_at) VALUES (?,?,?,?)",
                    (uid,partner["id"],content,now())
                )
                db.commit()
        return redirect(url_for("dm_user", username=username))

    # mark as read
    db.execute("UPDATE direct_messages SET is_read=1 WHERE sender_id=? AND receiver_id=?",
               (partner["id"],uid))
    db.commit()

    msgs = db.execute("""
        SELECT * FROM direct_messages
        WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
        ORDER BY id ASC LIMIT 100
    """,(uid,partner["id"],partner["id"],uid)).fetchall()

    msgs_html = ""
    for m in msgs:
        is_self = m["sender_id"] == uid
        col  = me["avatar_color"] if is_self else (partner["avatar_color"] or "#6366f1")
        init = avatar_initials(me["username"] if is_self else partner["username"])
        name = me["username"] if is_self else partner["username"]
        cls  = "msg-self" if is_self else ""
        msgs_html += f"""<div class="msg {cls}">
          <div class="avatar av-sm" style="background:{col}">{init}</div>
          <div class="msg-bubble">
            <div class="msg-header">
              <span class="msg-name" style="color:{col}">{name}</span>
              <span class="msg-time">{m['created_at'][11:16]}</span>
            </div>
            <div class="msg-text">{m['content']}</div>
          </div>
        </div>"""

    col2 = partner["avatar_color"] or "#6366f1"
    init2 = avatar_initials(partner["username"])

    input_html = ""
    if me["is_muted"]:
        input_html = '<div class="muted-notice">🔇 You are muted and cannot send messages.</div>'
    else:
        input_html = f"""<form class="chat-input-area" method="POST">
          <textarea class="chat-input" name="content" rows="1" placeholder="Message {partner['username']}..." required
            onkeydown="if(event.key==='Enter'&&!event.shiftKey){{event.preventDefault();this.form.submit()}}"></textarea>
          <button type="submit" class="btn btn-primary btn-sm">Send</button>
        </form>"""

    content = f"""
    <style>.page-body{{padding:0!important}}</style>
    <div style="padding:1rem 1.4rem;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:.9rem;background:var(--surface)">
      <a href="{url_for('dms')}" style="color:var(--text2);text-decoration:none;font-size:1.2rem">←</a>
      <div class="avatar av-sm" style="background:{col2}">{init2}</div>
      <div style="font-weight:700">{partner['username']}</div>
    </div>
    <div class="messages-area" id="msgs" style="max-height:calc(100vh - 180px)">{msgs_html}</div>
    {input_html}
    <script>const el=document.getElementById('msgs');el.scrollTop=el.scrollHeight;</script>"""

    return APP_BASE(f"DM — {username}", "dms", uid, content)

# ═══════════════════════════════════════════════════════════════════
#   SERVERS
# ═══════════════════════════════════════════════════════════════════
@app.route("/servers")
@login_required
def servers_page():
    uid = session["user_id"]
    db  = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    my_servers = db.execute("""
        SELECT s.*, sm.role,
          (SELECT COUNT(*) FROM server_members WHERE server_id=s.id) as member_count
        FROM servers s JOIN server_members sm ON sm.server_id=s.id
        WHERE sm.user_id=? ORDER BY s.name
    """,(uid,)).fetchall()
    msg = session.pop("srv_msg",None)

    srv_html = ""
    for s in my_servers:
        is_owner = s["owner_id"] == uid
        srv_html += f"""<div style="display:flex;align-items:center;gap:1rem;padding:1rem 0;border-bottom:1px solid var(--border)">
          <div class="avatar av-md" style="background:var(--indigo)">🖥️</div>
          <div style="flex:1">
            <div style="font-weight:700">{s['name']}</div>
            <div style="font-size:.82rem;color:var(--text2)">{s['description'] or ''}</div>
            <div style="margin-top:.3rem;display:flex;gap:.4rem">
              {'<span class="badge badge-purple">Owner</span>' if is_owner else '<span class="badge badge-indigo">Member</span>'}
              <span class="badge badge-teal">👥 {s['member_count']}</span>
            </div>
          </div>
          <a href="{url_for('server_view', server_id=s['id'])}" class="btn btn-secondary btn-sm">Open</a>
          {f'<form class="action-form" method="POST" action="{url_for("server_delete", server_id=s["id"])}" onsubmit="return confirm(\'Delete server?\')"><button type="submit" class="btn btn-danger btn-xs">Delete</button></form>' if is_owner else f'<form class="action-form" method="POST" action="{url_for("server_leave", server_id=s["id"])}"><button type="submit" class="btn btn-danger btn-xs">Leave</button></form>'}
        </div>"""

    content = f"""
    {'<div class="alert alert-success">'+msg+'</div>' if msg else ''}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.2rem;margin-bottom:1.2rem">
      <div class="card">
        <div class="card-title" style="margin-bottom:1rem">✨ Create Server</div>
        <div style="color:var(--text2);font-size:.88rem;margin-bottom:.8rem">
          Costs <span class="badge badge-amber">⬡ {SERVER_CREATE_COST} Tokens</span>
          — you have <strong style="color:var(--amber)">{user['tokens']}</strong> tokens.
        </div>
        {'<form method="POST" action="'+url_for('server_create')+'">' if user['tokens'] >= SERVER_CREATE_COST else '<div style="color:var(--red);font-size:.88rem">Not enough tokens.</div>'}
        {'<div class="form-group"><label class="form-label">Server Name</label><input class="form-input" type="text" name="name" placeholder="My Server" required></div><div class="form-group"><label class="form-label">Description (optional)</label><input class="form-input" type="text" name="description" placeholder="What\'s this server about?"></div><button type="submit" class="btn btn-primary">Create Server</button></form>' if user['tokens'] >= SERVER_CREATE_COST else ''}
      </div>
      <div class="card">
        <div class="card-title" style="margin-bottom:1rem">🔗 Join via Invite</div>
        <form method="POST" action="{url_for('server_join')}">
          <div class="form-group">
            <label class="form-label">Invite Code</label>
            <input class="form-input" type="text" name="code" placeholder="abc123" required>
          </div>
          <button type="submit" class="btn btn-primary">Join Server</button>
        </form>
      </div>
    </div>

    <div class="card">
      <div class="card-header"><div class="card-title">🖥️ Your Servers ({len(my_servers)})</div></div>
      {srv_html if srv_html else '<div class="empty"><div class="empty-icon">🖥️</div>No servers yet. Create one or join via invite!</div>'}
    </div>"""

    return APP_BASE("Servers", "servers", uid, content)

@app.route("/servers/create", methods=["POST"])
@login_required
def server_create():
    uid  = session["user_id"]
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if user["tokens"] < SERVER_CREATE_COST:
        session["srv_msg"] = "Not enough tokens."
        return redirect(url_for("servers_page"))
    name = request.form.get("name","").strip()[:50]
    desc = request.form.get("description","").strip()[:200]
    if not name:
        return redirect(url_for("servers_page"))
    code = secrets.token_urlsafe(8)
    db.execute("INSERT INTO servers (name,description,owner_id,invite_code,created_at) VALUES (?,?,?,?,?)",
               (name,desc,uid,code,now()))
    db.execute("UPDATE users SET tokens=tokens-? WHERE id=?",(SERVER_CREATE_COST,uid))
    srv = db.execute("SELECT id FROM servers WHERE invite_code=?",(code,)).fetchone()
    db.execute("INSERT INTO server_members (server_id,user_id,role,joined_at) VALUES (?,?,?,?)",
               (srv["id"],uid,"owner",now()))
    db.commit()
    audit("server_create",f"Server '{name}' created",user_id=uid,actor=user["username"])
    session["srv_msg"] = f"Server '{name}' created! Invite code: {code}"
    return redirect(url_for("server_view", server_id=srv["id"]))

@app.route("/servers/join", methods=["POST"])
@login_required
def server_join():
    uid  = session["user_id"]
    code = request.form.get("code","").strip()
    db   = get_db()
    srv  = db.execute("SELECT * FROM servers WHERE invite_code=?",(code,)).fetchone()
    if not srv:
        session["srv_msg"] = "Invalid invite code."
    elif db.execute("SELECT id FROM server_members WHERE server_id=? AND user_id=?",(srv["id"],uid)).fetchone():
        session["srv_msg"] = "You're already in this server."
    else:
        db.execute("INSERT INTO server_members (server_id,user_id,role,joined_at) VALUES (?,?,?,?)",
                   (srv["id"],uid,"member",now()))
        db.commit()
        session["srv_msg"] = f"Joined '{srv['name']}'!"
        return redirect(url_for("server_view", server_id=srv["id"]))
    return redirect(url_for("servers_page"))

@app.route("/servers/<int:server_id>")
@login_required
def server_view(server_id):
    uid = session["user_id"]
    db  = get_db()
    srv = db.execute("SELECT * FROM servers WHERE id=?",(server_id,)).fetchone()
    if not srv:
        return redirect(url_for("servers_page"))
    mem = db.execute("SELECT * FROM server_members WHERE server_id=? AND user_id=?",(server_id,uid)).fetchone()
    if not mem:
        return redirect(url_for("servers_page"))

    msgs = db.execute("""
        SELECT sm.*, u.avatar_color FROM server_messages sm
        JOIN users u ON u.id=sm.user_id
        WHERE sm.server_id=? ORDER BY sm.id ASC LIMIT 80
    """,(server_id,)).fetchall()

    members = db.execute("""
        SELECT u.*, sm.role FROM users u
        JOIN server_members sm ON sm.user_id=u.id
        WHERE sm.server_id=? ORDER BY sm.role DESC, u.username ASC
    """,(server_id,)).fetchall()

    me = db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()

    msgs_html = ""
    for m in msgs:
        col  = m["avatar_color"] or "#6366f1"
        init = avatar_initials(m["username"])
        is_self = m["user_id"] == uid
        cls  = "msg-self" if is_self else ""
        msgs_html += f"""<div class="msg {cls}">
          <div class="avatar av-sm" style="background:{col}">{init}</div>
          <div class="msg-bubble">
            <div class="msg-header">
              <span class="msg-name" style="color:{col}">{m['username']}</span>
              <span class="msg-time">{m['created_at'][11:16]}</span>
            </div>
            <div class="msg-text">{m['content']}</div>
          </div>
        </div>"""

    members_html = ""
    for mbr in members:
        col  = mbr["avatar_color"] or "#6366f1"
        init = avatar_initials(mbr["username"])
        role_badge = '<span class="badge badge-purple">Owner</span>' if mbr["role"]=="owner" else '<span class="badge badge-indigo">Member</span>'
        members_html += f"""<div style="display:flex;align-items:center;gap:.7rem;padding:.55rem .8rem">
          <div class="avatar av-sm" style="background:{col}">{init}</div>
          <div style="flex:1;font-size:.88rem;font-weight:600">{mbr['username']}</div>
          {role_badge}
        </div>"""

    if me["is_muted"]:
        input_html = '<div class="muted-notice">🔇 You are muted.</div>'
    else:
        input_html = f"""<form class="chat-input-area" method="POST" action="{url_for('server_chat_post', server_id=server_id)}">
          <textarea class="chat-input" name="content" rows="1" placeholder="Message #{srv['name']}..." required
            onkeydown="if(event.key==='Enter'&&!event.shiftKey){{event.preventDefault();this.form.submit()}}"></textarea>
          <button type="submit" class="btn btn-primary btn-sm">Send</button>
        </form>"""

    is_owner = srv["owner_id"] == uid
    invite_info = f'<span style="font-size:.8rem;color:var(--text3)">Invite: <span class="mono" style="color:var(--indigo)">{srv["invite_code"]}</span></span>' if is_owner else ""

    content = f"""
    <style>.page-body{{padding:0!important}}</style>
    <div style="display:flex;gap:0;height:calc(100vh - var(--topbar-h))">
      <div style="flex:1;display:flex;flex-direction:column;overflow:hidden">
        <div style="padding:.8rem 1.2rem;border-bottom:1px solid var(--border);background:var(--surface);display:flex;align-items:center;gap:1rem">
          <a href="{url_for('servers_page')}" style="color:var(--text2);text-decoration:none">← Back</a>
          <div style="font-weight:700"># {srv['name']}</div>
          {invite_info}
          {'<a href="'+url_for('server_delete',server_id=server_id)+'" style="margin-left:auto"><form class="action-form" method="POST" action="'+url_for('server_delete',server_id=server_id)+'" onsubmit="return confirm(\'Delete server?\')"><button type="submit" class="btn btn-danger btn-xs">Delete</button></form></a>' if is_owner else '<form class="action-form" style="margin-left:auto" method="POST" action="'+url_for('server_leave',server_id=server_id)+'"><button type="submit" class="btn btn-danger btn-xs">Leave</button></form>'}
        </div>
        <div class="messages-area" id="msgs">{msgs_html if msgs_html else '<div class="empty" style="margin-top:2rem"><div class="empty-icon">💬</div>No messages yet</div>'}</div>
        {input_html}
      </div>
      <div class="chat-panel">
        <div style="padding:.9rem 1rem;border-bottom:1px solid var(--border);font-size:.8rem;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.1em">
          Members — {len(members)}
        </div>
        {members_html}
      </div>
    </div>
    <script>const el=document.getElementById('msgs');if(el)el.scrollTop=el.scrollHeight;</script>"""

    return APP_BASE(srv["name"], "servers", uid, content)

@app.route("/servers/<int:server_id>/post", methods=["POST"])
@login_required
def server_chat_post(server_id):
    uid  = session["user_id"]
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if user["is_muted"]:
        return redirect(url_for("server_view", server_id=server_id))
    mem = db.execute("SELECT id FROM server_members WHERE server_id=? AND user_id=?",(server_id,uid)).fetchone()
    if not mem:
        return redirect(url_for("servers_page"))
    content = request.form.get("content","").strip()
    if content and len(content) <= 2000:
        db.execute("INSERT INTO server_messages (server_id,user_id,username,content,created_at) VALUES (?,?,?,?,?)",
                   (server_id,uid,user["username"],content,now()))
        db.commit()
    return redirect(url_for("server_view", server_id=server_id))

@app.route("/servers/<int:server_id>/delete", methods=["POST"])
@login_required
def server_delete(server_id):
    uid = session["user_id"]
    db  = get_db()
    srv = db.execute("SELECT * FROM servers WHERE id=? AND owner_id=?",(server_id,uid)).fetchone()
    if srv:
        db.execute("DELETE FROM server_messages WHERE server_id=?",(server_id,))
        db.execute("DELETE FROM server_members WHERE server_id=?",(server_id,))
        db.execute("DELETE FROM servers WHERE id=?",(server_id,))
        db.commit()
        session["srv_msg"] = f"Server '{srv['name']}' deleted."
    return redirect(url_for("servers_page"))

@app.route("/servers/<int:server_id>/leave", methods=["POST"])
@login_required
def server_leave(server_id):
    uid = session["user_id"]
    db  = get_db()
    db.execute("DELETE FROM server_members WHERE server_id=? AND user_id=?",(server_id,uid))
    db.commit()
    session["srv_msg"] = "Left server."
    return redirect(url_for("servers_page"))

# ═══════════════════════════════════════════════════════════════════
#   TICKETS
# ═══════════════════════════════════════════════════════════════════
@app.route("/tickets")
@login_required
def tickets():
    uid = session["user_id"]
    db  = get_db()
    my_tickets = db.execute(
        "SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC",(uid,)).fetchall()
    msg = session.pop("ticket_msg",None)

    tix_html = ""
    for t in my_tickets:
        status_badge = '<span class="badge badge-green">Open</span>' if t["status"]=="open" else '<span class="badge badge-red">Closed</span>'
        tix_html += f"""<div class="ticket-item">
          <div>
            <div style="font-weight:700">{t['subject']}</div>
            <div style="font-size:.8rem;color:var(--text3)">{t['created_at'][:10]}</div>
          </div>
          <div style="display:flex;align-items:center;gap:.8rem">
            {status_badge}
            <a href="{url_for('ticket_view', ticket_id=t['id'])}" class="btn btn-secondary btn-sm">Open →</a>
          </div>
        </div>"""

    content = f"""
    {'<div class="alert alert-success">'+msg+'</div>' if msg else ''}
    <div class="card">
      <div class="card-title" style="margin-bottom:1rem">🎫 Create Ticket</div>
      <form method="POST" action="{url_for('ticket_create')}">
        <div class="form-group">
          <label class="form-label">Subject</label>
          <input class="form-input" type="text" name="subject" placeholder="Brief description of your issue" required>
        </div>
        <div class="form-group">
          <label class="form-label">Message</label>
          <textarea class="form-input" name="content" rows="4" placeholder="Describe your issue in detail..." required style="resize:vertical"></textarea>
        </div>
        <button type="submit" class="btn btn-primary">Submit Ticket</button>
      </form>
    </div>

    <div class="card">
      <div class="card-header"><div class="card-title">🎫 My Tickets ({len(my_tickets)})</div></div>
      {tix_html if tix_html else '<div class="empty"><div class="empty-icon">🎫</div>No tickets yet.</div>'}
    </div>"""

    return APP_BASE("Support Tickets", "tickets", uid, content)

@app.route("/tickets/create", methods=["POST"])
@login_required
def ticket_create():
    uid     = session["user_id"]
    uname   = session["username"]
    subject = request.form.get("subject","").strip()
    content = request.form.get("content","").strip()
    if not subject or not content:
        return redirect(url_for("tickets"))
    db = get_db()
    db.execute("INSERT INTO tickets (user_id,subject,status,created_at) VALUES (?,?,?,?)",
               (uid,subject,"open",now()))
    t = db.execute("SELECT id FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 1",(uid,)).fetchone()
    db.execute("INSERT INTO ticket_messages (ticket_id,sender_id,sender_name,is_admin,content,created_at) VALUES (?,?,?,?,?,?)",
               (t["id"],uid,uname,0,content,now()))
    db.commit()
    session["ticket_msg"] = "Ticket submitted! An admin will respond soon."
    return redirect(url_for("ticket_view", ticket_id=t["id"]))

@app.route("/tickets/<int:ticket_id>", methods=["GET","POST"])
@login_required
def ticket_view(ticket_id):
    uid   = session["user_id"]
    uname = session["username"]
    db    = get_db()
    t     = db.execute("SELECT * FROM tickets WHERE id=? AND user_id=?",(ticket_id,uid)).fetchone()
    if not t:
        return redirect(url_for("tickets"))

    if request.method == "POST" and t["status"]=="open":
        content = request.form.get("content","").strip()
        if content:
            db.execute("INSERT INTO ticket_messages (ticket_id,sender_id,sender_name,is_admin,content,created_at) VALUES (?,?,?,?,?,?)",
                       (ticket_id,uid,uname,0,content,now()))
            db.commit()
        return redirect(url_for("ticket_view", ticket_id=ticket_id))

    msgs = db.execute("SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY id ASC",(ticket_id,)).fetchall()

    msgs_html = ""
    for m in msgs:
        if m["is_admin"]:
            style = "background:rgba(99,102,241,.08);border:1px solid rgba(99,102,241,.2);border-radius:12px;padding:.8rem 1rem;margin-bottom:.7rem"
            name_color = "var(--indigo)"
            label = " <span class='badge badge-indigo'>Admin</span>"
        else:
            style = "background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:.8rem 1rem;margin-bottom:.7rem"
            name_color = "var(--text)"
            label = ""
        msgs_html += f"""<div style="{style}">
          <div style="font-size:.8rem;font-weight:700;margin-bottom:.3rem;color:{name_color}">{m['sender_name']}{label} <span style="color:var(--text3);font-weight:400">{m['created_at'][11:16]}</span></div>
          <div style="font-size:.93rem;color:var(--text2)">{m['content']}</div>
        </div>"""

    status_badge = '<span class="badge badge-green">Open</span>' if t["status"]=="open" else '<span class="badge badge-red">Closed</span>'

    input_html = ""
    if t["status"]=="open":
        input_html = f"""<form method="POST" style="margin-top:1rem">
          <textarea class="form-input" name="content" rows="3" placeholder="Reply to this ticket..." required style="resize:vertical;margin-bottom:.6rem"></textarea>
          <button type="submit" class="btn btn-primary btn-sm">Send Reply</button>
        </form>"""

    content = f"""
    <div style="margin-bottom:1rem">
      <a href="{url_for('tickets')}" style="color:var(--text2);text-decoration:none;font-size:.9rem">← Back to Tickets</a>
    </div>
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1.2rem">
        <div>
          <div style="font-size:1.2rem;font-weight:800">{t['subject']}</div>
          <div style="font-size:.8rem;color:var(--text3)">Ticket #{t['id']} · {t['created_at'][:10]}</div>
        </div>
        {status_badge}
      </div>
      <div style="max-height:400px;overflow-y:auto;margin-bottom:.5rem">{msgs_html}</div>
      {input_html if input_html else '<div style="color:var(--text3);font-size:.88rem;margin-top:.8rem">This ticket is closed.</div>'}
    </div>"""

    return APP_BASE(f"Ticket #{ticket_id}", "tickets", uid, content)

# ═══════════════════════════════════════════════════════════════════
#   PROFILE & SETTINGS
# ═══════════════════════════════════════════════════════════════════
@app.route("/profile", methods=["GET","POST"])
@login_required
def profile():
    uid   = session["user_id"]
    uname = session["username"]
    db    = get_db()
    user  = db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    msg   = session.pop("profile_msg",None)
    err   = session.pop("profile_err",None)
    col   = user["avatar_color"] or "#6366f1"
    init  = avatar_initials(user["username"])
    try:
        is_premium = user["is_premium"]
    except Exception:
        is_premium = 0

    premium_section = ""
    if is_premium:
        premium_section = '''<div class="card" style="border-color:rgba(245,158,11,.3);background:linear-gradient(135deg,rgba(245,158,11,.05),rgba(236,72,153,.05))">
          <div style="display:flex;align-items:center;gap:.8rem">
            <div style="font-size:2rem">✦</div>
            <div>
              <div style="font-weight:800;font-size:1.1rem;background:linear-gradient(135deg,#f59e0b,#ec4899);-webkit-background-clip:text;-webkit-text-fill-color:transparent">Nexus Premium</div>
              <div style="color:var(--text2);font-size:.88rem;margin-top:.2rem">✓ Unlimited servers &nbsp;✓ Unlimited tokens &nbsp;✓ Exclusive PRO badge &nbsp;✓ Priority support</div>
            </div>
          </div>
        </div>'''
    else:
        premium_section = f'''<div class="card" style="border-color:rgba(245,158,11,.2)">
          <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:1rem">
            <div>
              <div style="font-weight:800;font-size:1rem">✦ Nexus Premium</div>
              <div style="color:var(--text2);font-size:.85rem;margin-top:.3rem">Unlimited servers · More tokens · PRO badge · Priority support</div>
            </div>
            <span class="badge badge-amber" style="font-size:.8rem;padding:.4rem .8rem">Ask an Admin to upgrade you</span>
          </div>
        </div>'''

    content = f"""
    {'<div class="alert alert-success">✓ '+msg+'</div>' if msg else ''}
    {'<div class="alert alert-error">⚠ '+err+'</div>' if err else ''}
    {premium_section}

    <div class="profile-header">
      {render_avatar(user, "av-xl")}
      <div>
        <div style="font-size:1.6rem;font-weight:800">{user['username']}{'  <span style="font-size:.75rem;background:linear-gradient(135deg,#f59e0b,#ec4899);color:#fff;padding:.2rem .5rem;border-radius:99px;font-weight:800">✦ PRO</span>' if is_premium else ''}</div>
        <div style="color:var(--text2)">{user['email']}</div>
        <div style="margin-top:.5rem;display:flex;gap:.5rem">
          <span class="badge badge-amber">⬡ {user['tokens']} Tokens</span>
          <span class="badge badge-indigo">Since {user['created_at'][:10]}</span>
        </div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.2rem">
      <div class="card">
        <div class="card-title" style="margin-bottom:1rem">✏️ Change Username</div>
        <form method="POST" action="{url_for('change_username')}">
          <div class="form-group">
            <label class="form-label">New Username</label>
            <input class="form-input" type="text" name="new_username" value="{user['username']}" required minlength="3">
          </div>
          <div class="form-group">
            <label class="form-label">Current Password (verification)</label>
            <input class="form-input" type="password" name="password" placeholder="••••••••" required>
          </div>
          <button type="submit" class="btn btn-primary btn-sm">Update Username</button>
        </form>
      </div>
      <div class="card">
        <div class="card-title" style="margin-bottom:1rem">📧 Change Email</div>
        <form method="POST" action="{url_for('change_email')}">
          <div class="form-group">
            <label class="form-label">New Email</label>
            <input class="form-input" type="email" name="new_email" required>
          </div>
          <div class="form-group">
            <label class="form-label">Current Password (verification)</label>
            <input class="form-input" type="password" name="password" placeholder="••••••••" required>
          </div>
          <button type="submit" class="btn btn-primary btn-sm">Update Email</button>
        </form>
      </div>
      <div class="card">
        <div class="card-title" style="margin-bottom:1rem">🔒 Change Password</div>
        <form method="POST" action="{url_for('change_password')}">
          <div class="form-group">
            <label class="form-label">Current Password</label>
            <input class="form-input" type="password" name="old_password" placeholder="••••••••" required>
          </div>
          <div class="form-group">
            <label class="form-label">New Password</label>
            <input class="form-input" type="password" name="new_password" placeholder="Min. 6 characters" required minlength="6">
          </div>
          <div class="form-group">
            <label class="form-label">Confirm New Password</label>
            <input class="form-input" type="password" name="confirm_password" placeholder="••••••••" required>
          </div>
          <button type="submit" class="btn btn-primary btn-sm">Update Password</button>
        </form>
      </div>
      <div class="card">
        <div class="card-title" style="margin-bottom:1rem">🎨 Avatar Color</div>
        <form method="POST" action="{url_for('change_color')}">
          <div style="display:flex;flex-wrap:wrap;gap:.6rem;margin-bottom:1rem">
            {''.join([f"""<label style="cursor:pointer">
              <input type="radio" name="color" value="{c}" {'checked' if c==col else ''} style="display:none">
              <div style="width:36px;height:36px;border-radius:50%;background:{c};
                          border:3px solid {'white' if c==col else 'transparent'};transition:border .2s"
                   onclick="this.parentElement.querySelector('input').checked=true"></div>
            </label>""" for c in AVATAR_COLORS])}
          </div>
          <button type="submit" class="btn btn-secondary btn-sm">Save Color</button>
        </form>
      </div>
      <div class="card">
        <div class="card-title" style="margin-bottom:1rem">🖼️ Profile Picture</div>
        <div style="display:flex;align-items:center;gap:1rem;margin-bottom:1rem">
          {render_avatar(user, "av-lg")}
          <div style="font-size:.85rem;color:var(--text2)">Upload a custom profile picture (JPG/PNG, max 1MB)</div>
        </div>
        <form method="POST" action="{url_for('change_avatar')}" enctype="multipart/form-data">
          <div style="display:flex;gap:.6rem;align-items:center;flex-wrap:wrap">
            <input type="file" name="avatar" accept="image/jpeg,image/png,image/gif,image/webp"
                   style="color:var(--text2);font-size:.85rem;flex:1">
            <button type="submit" class="btn btn-primary btn-sm">Upload</button>
          </div>
        </form>
        {'<form method="POST" action="'+url_for('remove_avatar')+'"><button type="submit" class="btn btn-danger btn-xs" style="margin-top:.6rem">Remove Picture</button></form>' if user.get('avatar_data') else ''}
      </div>
    </div>"""

    return APP_BASE("Profile", "profile", uid, content)

@app.route("/profile/username", methods=["POST"])
@login_required
def change_username():
    uid = session["user_id"]
    db  = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    new_name = request.form.get("new_username","").strip()
    password = request.form.get("password","")
    if not check_password_hash(user["password_hash"], password):
        session["profile_err"] = "Wrong password."
    elif len(new_name) < 3:
        session["profile_err"] = "Username too short."
    elif db.execute("SELECT id FROM users WHERE username=? AND id!=?",(new_name,uid)).fetchone():
        session["profile_err"] = "Username already taken."
    else:
        old = user["username"]
        db.execute("UPDATE users SET username=? WHERE id=?",(new_name,uid))
        db.commit()
        session["username"] = new_name
        audit("change_username",f"{old} → {new_name}",user_id=uid,actor=old)
        session["profile_msg"] = f"Username changed to '{new_name}'."
    return redirect(url_for("profile"))

@app.route("/profile/email", methods=["POST"])
@login_required
def change_email():
    uid = session["user_id"]
    db  = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    new_email = request.form.get("new_email","").strip().lower()
    password  = request.form.get("password","")
    if not check_password_hash(user["password_hash"], password):
        session["profile_err"] = "Wrong password."
    elif "@" not in new_email:
        session["profile_err"] = "Invalid email."
    elif db.execute("SELECT id FROM users WHERE email=? AND id!=?",(new_email,uid)).fetchone():
        session["profile_err"] = "Email already in use."
    else:
        if MAIL_ENABLED:
            token = secrets.token_urlsafe(32)
            db.execute("DELETE FROM email_tokens WHERE user_id=? AND type='email_change'",(uid,))
            db.execute("INSERT INTO email_tokens (user_id,token,type,data,created_at) VALUES (?,?,?,?,?)",
                       (uid,token,"email_change",new_email,now()))
            db.commit()
            link = f"{request.host_url}profile/confirm-email/{token}"
            send_email(new_email, f"Confirm your email — {SITE_TITLE}",
                       f"<p>Click to confirm: <a href='{link}'>{link}</a></p>")
            session["profile_msg"] = "Confirmation email sent! Check your inbox."
        else:
            old = user["email"]
            db.execute("UPDATE users SET email=? WHERE id=?",(new_email,uid))
            db.commit()
            audit("change_email",f"{old} → {new_email}",user_id=uid,actor=user["username"])
            session["profile_msg"] = f"Email updated to '{new_email}'."
    return redirect(url_for("profile"))

@app.route("/profile/confirm-email/<token>")
def confirm_email_change(token):
    db = get_db()
    rec = db.execute("SELECT * FROM email_tokens WHERE token=? AND type='email_change'",(token,)).fetchone()
    if not rec:
        return AUTH_BASE("Error", '<div class="alert alert-error">Invalid or expired link.</div>')
    db.execute("UPDATE users SET email=? WHERE id=?",(rec["data"],rec["user_id"]))
    db.execute("DELETE FROM email_tokens WHERE id=?",(rec["id"],))
    db.commit()
    return redirect(url_for("login"))

@app.route("/profile/password", methods=["POST"])
@login_required
def change_password():
    uid = session["user_id"]
    db  = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    old_pw  = request.form.get("old_password","")
    new_pw  = request.form.get("new_password","")
    conf_pw = request.form.get("confirm_password","")
    if not check_password_hash(user["password_hash"], old_pw):
        session["profile_err"] = "Current password is wrong."
    elif len(new_pw) < 6:
        session["profile_err"] = "New password too short."
    elif new_pw != conf_pw:
        session["profile_err"] = "Passwords do not match."
    else:
        db.execute("UPDATE users SET password_hash=? WHERE id=?",(generate_password_hash(new_pw),uid))
        db.commit()
        audit("change_password","Password changed",user_id=uid,actor=user["username"])
        session["profile_msg"] = "Password updated successfully."
    return redirect(url_for("profile"))

@app.route("/profile/color", methods=["POST"])
@login_required
def change_color():
    uid   = session["user_id"]
    color = request.form.get("color","#6366f1")
    if color not in AVATAR_COLORS:
        color = "#6366f1"
    db = get_db()
    db.execute("UPDATE users SET avatar_color=? WHERE id=?",(color,uid))
    db.commit()
    session["profile_msg"] = "Avatar color updated."
    return redirect(url_for("profile"))


@app.route("/profile/avatar", methods=["POST"])
@login_required
def change_avatar():
    uid = session["user_id"]
    f   = request.files.get("avatar")
    if not f or f.filename == "":
        session["profile_err"] = "No file selected."
        return redirect(url_for("profile"))
    data = f.read()
    if len(data) > 1.5 * 1024 * 1024:
        session["profile_err"] = "File too large (max 1MB)."
        return redirect(url_for("profile"))
    import base64, mimetypes
    mime = f.mimetype or "image/jpeg"
    b64  = base64.b64encode(data).decode()
    data_url = f"data:{mime};base64,{b64}"
    db = get_db()
    db.execute("UPDATE users SET avatar_data=? WHERE id=?", (data_url, uid))
    db.commit()
    session["profile_msg"] = "Profile picture updated!"
    return redirect(url_for("profile"))

@app.route("/profile/avatar/remove", methods=["POST"])
@login_required
def remove_avatar():
    uid = session["user_id"]
    db  = get_db()
    db.execute("UPDATE users SET avatar_data=NULL WHERE id=?", (uid,))
    db.commit()
    session["profile_msg"] = "Profile picture removed."
    return redirect(url_for("profile"))

@app.route("/page/<slug>")
@login_required
def custom_page_view(slug):
    uid = session["user_id"]
    db  = get_db()
    page = db.execute("SELECT * FROM custom_pages WHERE slug=?", (slug,)).fetchone()
    if not page:
        return redirect(url_for("dashboard"))
    content = f'''<div class="card">
      <div style="font-size:2rem;margin-bottom:.5rem">{page["icon"]}</div>
      <div style="font-size:1.5rem;font-weight:800;margin-bottom:1rem">{page["title"]}</div>
      <div style="color:var(--text2);line-height:1.8;white-space:pre-wrap">{page["content"]}</div>
    </div>'''
    return APP_BASE(page["title"], f"page_{slug}", uid, content)

# ═══════════════════════════════════════════════════════════════════
#   BANNED PAGE
# ═══════════════════════════════════════════════════════════════════
@app.route("/banned")
def banned_page():
    body = f"""<!DOCTYPE html><html lang="de"><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Banned</title>{BASE_CSS}</head><body>
    <div class="banned-page">
      <div style="font-size:5rem;margin-bottom:1rem;animation:fadeIn 1s">⛔</div>
      <div style="font-size:2.5rem;font-weight:800;color:var(--red);margin-bottom:.5rem;letter-spacing:-.02em">Access Denied</div>
      <p style="color:var(--text2);max-width:380px;line-height:1.7">Your IP has been banned by an administrator. You no longer have access to this platform.</p>
      <div style="margin-top:1.5rem;font-family:'JetBrains Mono',monospace;color:var(--red);font-size:.85rem;opacity:.5">
        BANNED IP: {get_ip()}
      </div>
    </div></body></html>"""
    return body, 403

# ═══════════════════════════════════════════════════════════════════
#   ADMIN PANEL
# ═══════════════════════════════════════════════════════════════════

def admin_layout(title, content, tab=""):
    tabs = [
        ("users","Users"),("bans","Bans"),("tokens","Tokens"),
        ("tickets","Tickets"),("audit","Audit Log"),("premium","Premium"),("pages","Pages"),
    ]
    tabs_html = "".join([
        f'<a href="/admin?tab={k}" class="tab{" active" if tab==k else ""}">{v}</a>'
        for k,v in tabs
    ])
    msg = session.pop("admin_msg",None)
    alert = f'<div class="alert alert-success" style="margin-bottom:1.2rem">✓ {msg}</div>' if msg else ""

    return f"""<!DOCTYPE html><html lang="de"><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{title} — Admin</title>{BASE_CSS}</head><body>
    <div class="admin-topbar">
      <div style="display:flex;align-items:center;gap:.8rem">
        <div class="logo-icon">✦</div>
        <div>
          <div style="font-weight:800;font-size:1rem">{SITE_TITLE} Admin</div>
          <div style="font-size:.72rem;color:var(--text3)">Control Panel</div>
        </div>
      </div>
      <div style="display:flex;gap:.6rem">
        <a href="/" class="btn btn-secondary btn-sm">← Site</a>
        <a href="/admin/logout" class="btn btn-danger btn-sm">Logout</a>
      </div>
    </div>
    <div class="admin-body">
      <div class="tab-bar">{tabs_html}</div>
      {alert}
      {content}
    </div>
    </body></html>"""

@app.route("/admin")
@admin_required
def admin():
    db  = get_db()
    tab = request.args.get("tab","users")

    users = db.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    bans  = db.execute("SELECT * FROM bans ORDER BY id DESC").fetchall()

    total_users = len(users)
    total_bans  = len(bans)
    today_users = sum(1 for u in users if u["created_at"].startswith(today()))

    if tab == "users":
        rows = ""
        for u in users:
            mute_badge = '<span class="badge badge-red">Muted</span>' if u["is_muted"] else '<span class="badge badge-green">Active</span>'
            rows += f"""<tr>
              <td class="mono" style="color:var(--text3)">#{u['id']}</td>
              <td style="font-weight:700">{u['username']}</td>
              <td style="color:var(--text2)">{u['email']}</td>
              <td class="mono" style="font-size:.78rem;color:var(--text3)">{u['ip'] or '—'}</td>
              <td><span class="badge badge-amber">⬡ {u['tokens']}</span></td>
              <td>{mute_badge}</td>
              <td style="color:var(--text3);font-size:.78rem">{u['created_at'][:10]}</td>
              <td style="white-space:nowrap">
                <a href="/admin/user/{u['id']}" class="btn btn-secondary btn-xs">Edit</a>
                <form class="action-form" method="POST" action="/admin/kick/{u['id']}"
                      onsubmit="return confirm('Kick {u['username']}?')">
                  <button type="submit" class="btn btn-amber btn-xs">Kick</button>
                </form>
                <form class="action-form" method="POST" action="/admin/ban/{u['id']}">
                  <input type="text" name="reason" class="reason-input" placeholder="Reason...">
                  <button type="submit" class="btn btn-danger btn-xs"
                          onclick="return confirm('Ban {u['username']}?')">Ban</button>
                </form>
                {'<form class="action-form" method="POST" action="/admin/unmute/'+str(u['id'])+'"><button type="submit" class="btn btn-success btn-xs">Unmute</button></form>' if u['is_muted'] else '<form class="action-form" method="POST" action="/admin/mute/'+str(u['id'])+'"><input type="text" name="reason" class="reason-input" placeholder="Mute reason..."><button type="submit" class="btn btn-amber btn-xs">Mute</button></form>'}
              </td>
            </tr>"""
        content = f"""
        <div class="stat-grid" style="margin-bottom:1.5rem">
          <div class="stat-card"><div class="stat-label">Total Users</div><div class="stat-value" style="color:var(--indigo)">{total_users}</div></div>
          <div class="stat-card"><div class="stat-label">Today</div><div class="stat-value" style="color:var(--amber)">{today_users}</div></div>
          <div class="stat-card"><div class="stat-label">Active Bans</div><div class="stat-value" style="color:var(--red)">{total_bans}</div></div>
          <div class="stat-card"><div class="stat-label">DB</div><div style="font-family:'JetBrains Mono',monospace;font-size:.78rem;color:var(--text3);margin-top:.5rem">{DB_PATH}</div></div>
        </div>
        <div class="card" style="padding:0;overflow:hidden">
          <div class="table-wrap">
            <table class="data-table">
              <thead><tr><th>#</th><th>Username</th><th>Email</th><th>IP</th><th>Tokens</th><th>Status</th><th>Joined</th><th>Actions</th></tr></thead>
              <tbody>{rows if rows else '<tr><td colspan="8" style="text-align:center;padding:2rem;color:var(--text3)">No users</td></tr>'}</tbody>
            </table>
          </div>
        </div>"""

    elif tab == "bans":
        rows = ""
        for b in bans:
            rows += f"""<tr>
              <td><span class="badge badge-red">#{b['id']}</span></td>
              <td style="font-weight:700">{b['username']}</td>
              <td style="color:var(--text2)">{b['email']}</td>
              <td class="mono" style="font-size:.8rem">{b['ip']}</td>
              <td style="color:var(--text3)">{b['reason'] or '—'}</td>
              <td style="font-size:.78rem;color:var(--text3)">{b['banned_at'][:10]}</td>
              <td>
                <form class="action-form" method="POST" action="/admin/unban/{b['id']}"
                      onsubmit="return confirm('Unban {b['username']}?')">
                  <button type="submit" class="btn btn-success btn-xs">Unban</button>
                </form>
              </td>
            </tr>"""
        content = f"""<div class="card" style="padding:0;overflow:hidden">
          <div class="table-wrap">
            <table class="data-table">
              <thead><tr><th>ID</th><th>Username</th><th>Email</th><th>IP</th><th>Reason</th><th>Date</th><th>Action</th></tr></thead>
              <tbody>{rows if rows else '<tr><td colspan="7" style="text-align:center;padding:2rem;color:var(--text3)">No bans</td></tr>'}</tbody>
            </table>
          </div>
        </div>"""

    elif tab == "tokens":
        rows = ""
        for u in users:
            rows += f"""<tr>
              <td style="font-weight:700">{u['username']}</td>
              <td><span class="badge badge-amber">⬡ {u['tokens']}</span></td>
              <td>
                <form class="action-form" method="POST" action="/admin/tokens/{u['id']}">
                  <input type="number" name="amount" class="reason-input" placeholder="Amount" style="width:90px" min="1" max="9999">
                  <button type="submit" name="action" value="add" class="btn btn-success btn-xs">+ Add</button>
                  <button type="submit" name="action" value="remove" class="btn btn-danger btn-xs">− Remove</button>
                  <button type="submit" name="action" value="set" class="btn btn-amber btn-xs">= Set</button>
                </form>
              </td>
            </tr>"""
        content = f"""<div class="card" style="padding:0;overflow:hidden">
          <div class="table-wrap">
            <table class="data-table">
              <thead><tr><th>Username</th><th>Tokens</th><th>Actions</th></tr></thead>
              <tbody>{rows}</tbody>
            </table>
          </div>
        </div>"""

    elif tab == "tickets":
        all_tickets = db.execute("""
            SELECT t.*, u.username FROM tickets t
            JOIN users u ON u.id=t.user_id
            ORDER BY t.id DESC
        """).fetchall()
        rows = ""
        for t in all_tickets:
            status_b = '<span class="badge badge-green">Open</span>' if t["status"]=="open" else '<span class="badge badge-red">Closed</span>'
            rows += f"""<tr>
              <td class="mono" style="color:var(--text3)">#{t['id']}</td>
              <td style="font-weight:700">{t['username']}</td>
              <td>{t['subject']}</td>
              <td>{status_b}</td>
              <td style="font-size:.78rem;color:var(--text3)">{t['created_at'][:10]}</td>
              <td>
                <a href="/admin/ticket/{t['id']}" class="btn btn-secondary btn-xs">View/Reply</a>
                {f'<form class="action-form" method="POST" action="/admin/ticket/{t["id"]}/close"><button type="submit" class="btn btn-danger btn-xs">Close</button></form>' if t['status']=='open' else ''}
              </td>
            </tr>"""
        content = f"""<div class="card" style="padding:0;overflow:hidden">
          <div class="table-wrap">
            <table class="data-table">
              <thead><tr><th>#</th><th>User</th><th>Subject</th><th>Status</th><th>Date</th><th>Actions</th></tr></thead>
              <tbody>{rows if rows else '<tr><td colspan="6" style="text-align:center;padding:2rem;color:var(--text3)">No tickets</td></tr>'}</tbody>
            </table>
          </div>
        </div>"""

    elif tab == "audit":
        logs = db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200").fetchall()
        rows = ""
        for l in logs:
            rows += f"""<tr>
              <td class="mono" style="font-size:.78rem;color:var(--text3)">{l['created_at']}</td>
              <td style="font-weight:600">{l['actor']}</td>
              <td><span class="badge badge-indigo">{l['action']}</span></td>
              <td style="color:var(--text2);font-size:.88rem">{l['details'] or '—'}</td>
            </tr>"""
        content = f"""<div class="card" style="padding:0;overflow:hidden">
          <div class="table-wrap">
            <table class="data-table">
              <thead><tr><th>Timestamp</th><th>Actor</th><th>Action</th><th>Details</th></tr></thead>
              <tbody>{rows if rows else '<tr><td colspan="4" style="text-align:center;padding:2rem;color:var(--text3)">No logs</td></tr>'}</tbody>
            </table>
          </div>
        </div>"""
    elif tab == "premium":
        all_users = db.execute("SELECT u.*, CASE WHEN pu.id IS NOT NULL THEN 1 ELSE 0 END as is_premium FROM users u LEFT JOIN premium_users pu ON pu.user_id=u.id ORDER BY u.id DESC").fetchall()
        rows = ""
        for u in all_users:
            badge = '<span class="badge badge-amber">✦ PRO</span>' if u["is_premium"] else '<span class="badge" style="background:rgba(255,255,255,.05);color:var(--text3);border:1px solid var(--border)">Free</span>'
            btn = f'<form class="action-form" method="POST" action="/admin/premium/remove/{u["id"]}"><button type="submit" class="btn btn-danger btn-xs">Remove</button></form>' if u["is_premium"] else f'<form class="action-form" method="POST" action="/admin/premium/grant/{u["id"]}"><button type="submit" class="btn btn-amber btn-xs">✦ Grant PRO</button></form>'
            rows += f'''<tr>
              <td style="font-weight:700">{u["username"]}</td>
              <td style="color:var(--text2)">{u["email"]}</td>
              <td>{badge}</td>
              <td>{btn}</td>
            </tr>'''
        content = f'''<div class="card" style="padding:0;overflow:hidden">
          <div class="table-wrap">
            <table class="data-table">
              <thead><tr><th>Username</th><th>Email</th><th>Status</th><th>Action</th></tr></thead>
              <tbody>{rows}</tbody>
            </table>
          </div>
        </div>'''

    elif tab == "pages":
        pages = db.execute("SELECT * FROM custom_pages ORDER BY id DESC").fetchall()
        rows = ""
        for p in pages:
            rows += f'''<tr>
              <td>{p["icon"]} {p["title"]}</td>
              <td class="mono" style="color:var(--indigo)">/page/{p["slug"]}</td>
              <td>{"Shown" if p["show_sidebar"] else "Hidden"}</td>
              <td>
                <a href="/admin/pages/edit/{p["id"]}" class="btn btn-secondary btn-xs">Edit</a>
                <form class="action-form" method="POST" action="/admin/pages/delete/{p["id"]}" onsubmit="return confirm('Delete page?')">
                  <button type="submit" class="btn btn-danger btn-xs">Delete</button>
                </form>
              </td>
            </tr>'''
        content = f'''
        <div class="card">
          <div class="card-title" style="margin-bottom:1rem">➕ Create New Page</div>
          <form method="POST" action="/admin/pages/create">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:.8rem;margin-bottom:.8rem">
              <div>
                <label class="form-label">Page Title</label>
                <input class="form-input" type="text" name="title" placeholder="Announcements" required>
              </div>
              <div>
                <label class="form-label">URL Slug</label>
                <input class="form-input" type="text" name="slug" placeholder="announcements" required>
              </div>
              <div>
                <label class="form-label">Icon (emoji)</label>
                <input class="form-input" type="text" name="icon" placeholder="📢" value="📄" maxlength="4">
              </div>
              <div>
                <label class="form-label">Show in Sidebar</label>
                <select class="form-input" name="show_sidebar">
                  <option value="1">Yes</option>
                  <option value="0">No</option>
                </select>
              </div>
            </div>
            <label class="form-label">Content</label>
            <textarea class="form-input" name="content" rows="6" placeholder="Write your page content here..." required style="resize:vertical;margin-bottom:.8rem"></textarea>
            <button type="submit" class="btn btn-primary btn-sm">Create Page</button>
          </form>
        </div>
        <div class="card" style="padding:0;overflow:hidden">
          <div class="table-wrap">
            <table class="data-table">
              <thead><tr><th>Title</th><th>URL</th><th>Sidebar</th><th>Actions</th></tr></thead>
              <tbody>{rows if rows else '<tr><td colspan="4" style="text-align:center;padding:2rem;color:var(--text3)">No custom pages yet</td></tr>'}</tbody>
            </table>
          </div>
        </div>'''

    else:
        content = ""

    return admin_layout(f"Admin — {tab.title()}", content, tab)

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin"))
        error = "Wrong password."
    body = f"""
    <h2 class="auth-title">Admin Panel</h2>
    <p class="auth-sub">Authorized personnel only.</p>
    {'<div class="alert alert-error">'+error+'</div>' if error else ''}
    <form method="POST">
      <div class="form-group">
        <label class="form-label">Admin Password</label>
        <input class="form-input" type="password" name="password" placeholder="••••••••" required>
      </div>
      <button type="submit" class="btn btn-primary">Login</button>
    </form>
    <div style="text-align:center;margin-top:1rem">
      <a href="/" class="link">← Back to site</a>
    </div>"""
    return AUTH_BASE("Admin Login", body)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin",None)
    return redirect(url_for("index"))

@app.route("/admin/kick/<int:user_id>", methods=["POST"])
@admin_required
def admin_kick(user_id):
    db   = get_db()
    user = db.execute("SELECT username FROM users WHERE id=?",(user_id,)).fetchone()
    if user:
        db.execute("DELETE FROM users WHERE id=?",(user_id,))
        db.commit()
        audit("admin_kick",f"Kicked user {user['username']}",actor="Admin")
        session["admin_msg"] = f"User '{user['username']}' kicked."
    return redirect(url_for("admin",tab="users"))

@app.route("/admin/ban/<int:user_id>", methods=["POST"])
@admin_required
def admin_ban(user_id):
    db     = get_db()
    user   = db.execute("SELECT * FROM users WHERE id=?",(user_id,)).fetchone()
    reason = request.form.get("reason","").strip() or None
    if user:
        ip = user["ip"] or "unknown"
        if not db.execute("SELECT id FROM bans WHERE ip=?",(ip,)).fetchone():
            db.execute("INSERT INTO bans (ip,username,email,reason,banned_at) VALUES (?,?,?,?,?)",
                       (ip,user["username"],user["email"],reason,now()))
        db.execute("DELETE FROM users WHERE id=?",(user_id,))
        db.commit()
        audit("admin_ban",f"Banned {user['username']} (IP:{ip}) Reason:{reason}",actor="Admin")
        session["admin_msg"] = f"'{user['username']}' banned. IP {ip} blocked."
    return redirect(url_for("admin",tab="bans"))

@app.route("/admin/unban/<int:ban_id>", methods=["POST"])
@admin_required
def admin_unban(ban_id):
    db  = get_db()
    ban = db.execute("SELECT username,ip FROM bans WHERE id=?",(ban_id,)).fetchone()
    if ban:
        db.execute("DELETE FROM bans WHERE id=?",(ban_id,))
        db.commit()
        audit("admin_unban",f"Unbanned {ban['username']} (IP:{ban['ip']})",actor="Admin")
        session["admin_msg"] = f"Unbanned '{ban['username']}'."
    return redirect(url_for("admin",tab="bans"))

@app.route("/admin/mute/<int:user_id>", methods=["POST"])
@admin_required
def admin_mute(user_id):
    db     = get_db()
    user   = db.execute("SELECT username FROM users WHERE id=?",(user_id,)).fetchone()
    reason = request.form.get("reason","").strip() or None
    if user:
        db.execute("UPDATE users SET is_muted=1, mute_reason=? WHERE id=?",(reason,user_id))
        db.commit()
        audit("admin_mute",f"Muted {user['username']} Reason:{reason}",actor="Admin")
        session["admin_msg"] = f"'{user['username']}' muted."
    return redirect(url_for("admin",tab="users"))

@app.route("/admin/unmute/<int:user_id>", methods=["POST"])
@admin_required
def admin_unmute(user_id):
    db   = get_db()
    user = db.execute("SELECT username FROM users WHERE id=?",(user_id,)).fetchone()
    if user:
        db.execute("UPDATE users SET is_muted=0, mute_reason=NULL WHERE id=?",(user_id,))
        db.commit()
        audit("admin_unmute",f"Unmuted {user['username']}",actor="Admin")
        session["admin_msg"] = f"'{user['username']}' unmuted."
    return redirect(url_for("admin",tab="users"))

@app.route("/admin/tokens/<int:user_id>", methods=["POST"])
@admin_required
def admin_tokens(user_id):
    db     = get_db()
    user   = db.execute("SELECT * FROM users WHERE id=?",(user_id,)).fetchone()
    action = request.form.get("action","add")
    try:
        amount = int(request.form.get("amount",0))
    except ValueError:
        amount = 0
    if user and amount > 0:
        if action == "add":
            db.execute("UPDATE users SET tokens=tokens+? WHERE id=?",(amount,user_id))
            audit("admin_tokens",f"Added {amount} tokens to {user['username']}",actor="Admin")
        elif action == "remove":
            db.execute("UPDATE users SET tokens=MAX(0,tokens-?) WHERE id=?",(amount,user_id))
            audit("admin_tokens",f"Removed {amount} tokens from {user['username']}",actor="Admin")
        elif action == "set":
            db.execute("UPDATE users SET tokens=? WHERE id=?",(amount,user_id))
            audit("admin_tokens",f"Set {user['username']} tokens to {amount}",actor="Admin")
        db.commit()
        session["admin_msg"] = f"Tokens updated for '{user['username']}'."
    return redirect(url_for("admin",tab="tokens"))

@app.route("/admin/user/<int:user_id>", methods=["GET","POST"])
@admin_required
def admin_user_edit(user_id):
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?",(user_id,)).fetchone()
    if not user:
        return redirect(url_for("admin",tab="users"))

    msg = None
    err = None

    if request.method == "POST":
        action = request.form.get("action","")
        if action == "edit":
            new_username = request.form.get("username","").strip()
            new_email    = request.form.get("email","").strip().lower()
            new_pw       = request.form.get("new_password","").strip()
            if not new_username or not new_email:
                err = "Username and email are required."
            else:
                db.execute("UPDATE users SET username=?, email=? WHERE id=?",(new_username,new_email,user_id))
                audit("admin_edit",f"Edited user #{user_id}: username={new_username}, email={new_email}",actor="Admin")
                if new_pw:
                    if len(new_pw) < 6:
                        err = "New password too short."
                    else:
                        db.execute("UPDATE users SET password_hash=? WHERE id=?",(generate_password_hash(new_pw),user_id))
                        audit("admin_pw_reset",f"Admin reset password for #{user_id}",actor="Admin")
                if not err:
                    db.commit()
                    msg = "User updated."
                    user = db.execute("SELECT * FROM users WHERE id=?",(user_id,)).fetchone()

    # audit for this user
    logs = db.execute("SELECT * FROM audit_log WHERE user_id=? ORDER BY id DESC LIMIT 30",(user_id,)).fetchall()
    logs_html = "".join([f"""<tr>
      <td style="font-size:.78rem;color:var(--text3)">{l['created_at']}</td>
      <td style="font-weight:600">{l['actor']}</td>
      <td><span class="badge badge-indigo">{l['action']}</span></td>
      <td style="color:var(--text2);font-size:.88rem">{l['details'] or '—'}</td>
    </tr>""" for l in logs])

    content = f"""
    {'<div class="alert alert-success">✓ '+msg+'</div>' if msg else ''}
    {'<div class="alert alert-error">⚠ '+err+'</div>' if err else ''}
    <div style="margin-bottom:1rem"><a href="/admin?tab=users" class="btn btn-secondary btn-sm">← Back</a></div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.2rem;margin-bottom:1.5rem">
      <div class="card">
        <div class="card-title" style="margin-bottom:1.2rem">📋 User Info <span class="badge badge-indigo">#{user['id']}</span></div>
        <table style="width:100%;font-size:.88rem">
          <tr><td style="color:var(--text3);padding:.35rem 0">IP Address</td><td class="mono">{user['ip'] or '—'}</td></tr>
          <tr><td style="color:var(--text3);padding:.35rem 0">Tokens</td><td><span class="badge badge-amber">⬡ {user['tokens']}</span></td></tr>
          <tr><td style="color:var(--text3);padding:.35rem 0">Muted</td><td>{'<span class="badge badge-red">Yes</span>' if user['is_muted'] else '<span class="badge badge-green">No</span>'}</td></tr>
          <tr><td style="color:var(--text3);padding:.35rem 0">Joined</td><td>{user['created_at']}</td></tr>
        </table>
      </div>
      <div class="card">
        <div class="card-title" style="margin-bottom:1rem">✏️ Edit Account</div>
        <form method="POST">
          <input type="hidden" name="action" value="edit">
          <div class="form-group">
            <label class="form-label">Username</label>
            <input class="form-input" type="text" name="username" value="{user['username']}" required>
          </div>
          <div class="form-group">
            <label class="form-label">Email</label>
            <input class="form-input" type="email" name="email" value="{user['email']}" required>
          </div>
          <div class="form-group">
            <label class="form-label">New Password (leave blank to keep)</label>
            <input class="form-input" type="text" name="new_password" placeholder="Enter new password or leave blank" autocomplete="off">
          </div>
          <div style="font-size:.75rem;color:var(--text3);margin-bottom:.8rem">
            ⚠ Current password hash: <span class="mono" style="font-size:.7rem">{user['password_hash'][:40]}...</span>
          </div>
          <button type="submit" class="btn btn-primary btn-sm">Save Changes</button>
        </form>
      </div>
    </div>

    <div class="card">
      <div class="card-title" style="margin-bottom:1rem">📜 Change History</div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Details</th></tr></thead>
          <tbody>{logs_html if logs_html else '<tr><td colspan="4" style="text-align:center;padding:1.5rem;color:var(--text3)">No logs</td></tr>'}</tbody>
        </table>
      </div>
    </div>"""

    return admin_layout(f"Edit User — {user['username']}", content, "users")

@app.route("/admin/ticket/<int:ticket_id>", methods=["GET","POST"])
@admin_required
def admin_ticket_view(ticket_id):
    db = get_db()
    t  = db.execute("SELECT t.*, u.username FROM tickets t JOIN users u ON u.id=t.user_id WHERE t.id=?",(ticket_id,)).fetchone()
    if not t:
        return redirect(url_for("admin",tab="tickets"))

    if request.method == "POST":
        content = request.form.get("content","").strip()
        if content:
            db.execute("INSERT INTO ticket_messages (ticket_id,sender_id,sender_name,is_admin,content,created_at) VALUES (?,?,?,?,?,?)",
                       (ticket_id,0,"Admin",1,content,now()))
            db.commit()
        return redirect(url_for("admin_ticket_view",ticket_id=ticket_id))

    msgs = db.execute("SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY id ASC",(ticket_id,)).fetchall()
    msgs_html = ""
    for m in msgs:
        if m["is_admin"]:
            style = "background:rgba(99,102,241,.1);border:1px solid rgba(99,102,241,.2);border-radius:12px;padding:.8rem 1rem;margin-bottom:.7rem"
            nc = "var(--indigo)"; label = ' <span class="badge badge-indigo">Admin</span>'
        else:
            style = "background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:.8rem 1rem;margin-bottom:.7rem"
            nc = "var(--text)"; label = ""
        msgs_html += f'<div style="{style}"><div style="font-size:.8rem;font-weight:700;margin-bottom:.3rem;color:{nc}">{m["sender_name"]}{label} <span style="color:var(--text3);font-weight:400">{m["created_at"][11:16]}</span></div><div style="font-size:.93rem;color:var(--text2)">{m["content"]}</div></div>'

    status_b = '<span class="badge badge-green">Open</span>' if t["status"]=="open" else '<span class="badge badge-red">Closed</span>'

    content_html = f"""
    <div style="margin-bottom:1rem"><a href="/admin?tab=tickets" class="btn btn-secondary btn-sm">← Back</a></div>
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.2rem">
        <div>
          <div style="font-size:1.2rem;font-weight:800">#{t['id']} — {t['subject']}</div>
          <div style="font-size:.8rem;color:var(--text3)">From: <strong>{t['username']}</strong> · {t['created_at'][:10]}</div>
        </div>
        {status_b}
      </div>
      <div style="max-height:400px;overflow-y:auto;margin-bottom:1rem">{msgs_html}</div>
      {'<form method="POST"><textarea class="form-input" name="content" rows="3" placeholder="Admin reply..." required style="resize:vertical;margin-bottom:.6rem"></textarea><button type="submit" class="btn btn-primary btn-sm">Send Reply</button></form>' if t['status']=='open' else '<div style="color:var(--text3)">Ticket is closed.</div>'}
    </div>"""
    return admin_layout(f"Ticket #{ticket_id}", content_html, "tickets")

@app.route("/admin/ticket/<int:ticket_id>/close", methods=["POST"])
@admin_required
def admin_ticket_close(ticket_id):
    db = get_db()
    db.execute("UPDATE tickets SET status='closed', closed_at=? WHERE id=?",(now(),ticket_id))
    db.commit()
    session["admin_msg"] = f"Ticket #{ticket_id} closed."
    return redirect(url_for("admin",tab="tickets"))


@app.route("/admin/premium/grant/<int:user_id>", methods=["POST"])
@admin_required
def admin_premium_grant(user_id):
    db   = get_db()
    user = db.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
    if user:
        db.execute("INSERT OR IGNORE INTO premium_users (user_id,granted_at,granted_by) VALUES (?,?,?)", (user_id, now(), "Admin"))
        db.execute("UPDATE users SET is_premium=1 WHERE id=?", (user_id,))
        db.commit()
        audit("admin_premium_grant", f"Granted PRO to {user['username']}", actor="Admin")
        session["admin_msg"] = f"✦ PRO granted to '{user['username']}'."
    return redirect(url_for("admin", tab="premium"))

@app.route("/admin/premium/remove/<int:user_id>", methods=["POST"])
@admin_required
def admin_premium_remove(user_id):
    db   = get_db()
    user = db.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
    if user:
        db.execute("DELETE FROM premium_users WHERE user_id=?", (user_id,))
        db.execute("UPDATE users SET is_premium=0 WHERE id=?", (user_id,))
        db.commit()
        audit("admin_premium_remove", f"Removed PRO from {user['username']}", actor="Admin")
        session["admin_msg"] = f"PRO removed from '{user['username']}'."
    return redirect(url_for("admin", tab="premium"))

@app.route("/admin/pages/create", methods=["POST"])
@admin_required
def admin_page_create():
    title = request.form.get("title","").strip()
    slug  = request.form.get("slug","").strip().lower().replace(" ","-")
    icon  = request.form.get("icon","📄").strip() or "📄"
    body  = request.form.get("content","").strip()
    show  = int(request.form.get("show_sidebar","1"))
    if title and slug and body:
        db = get_db()
        try:
            db.execute("INSERT INTO custom_pages (title,slug,icon,content,show_sidebar,created_at) VALUES (?,?,?,?,?,?)",
                       (title, slug, icon, body, show, now()))
            db.commit()
            session["admin_msg"] = f"Page '{title}' created!"
        except Exception as e:
            session["admin_msg"] = f"Error: {e}"
    return redirect(url_for("admin", tab="pages"))

@app.route("/admin/pages/delete/<int:page_id>", methods=["POST"])
@admin_required
def admin_page_delete(page_id):
    db = get_db()
    page = db.execute("SELECT title FROM custom_pages WHERE id=?", (page_id,)).fetchone()
    if page:
        db.execute("DELETE FROM custom_pages WHERE id=?", (page_id,))
        db.commit()
        session["admin_msg"] = f"Page '{page['title']}' deleted."
    return redirect(url_for("admin", tab="pages"))

@app.route("/admin/pages/edit/<int:page_id>", methods=["GET","POST"])
@admin_required
def admin_page_edit(page_id):
    db   = get_db()
    page = db.execute("SELECT * FROM custom_pages WHERE id=?", (page_id,)).fetchone()
    if not page:
        return redirect(url_for("admin", tab="pages"))
    msg = None
    if request.method == "POST":
        title = request.form.get("title","").strip()
        icon  = request.form.get("icon","📄").strip() or "📄"
        body  = request.form.get("content","").strip()
        show  = int(request.form.get("show_sidebar","1"))
        if title and body:
            db.execute("UPDATE custom_pages SET title=?,icon=?,content=?,show_sidebar=? WHERE id=?",
                       (title, icon, body, show, page_id))
            db.commit()
            msg = "Page updated!"
            page = db.execute("SELECT * FROM custom_pages WHERE id=?", (page_id,)).fetchone()

    content_html = f"""
    <div style="margin-bottom:1rem"><a href="/admin?tab=pages" class="btn btn-secondary btn-sm">← Back</a></div>
    {'<div class="alert alert-success">✓ '+msg+'</div>' if msg else ''}
    <div class="card">
      <div class="card-title" style="margin-bottom:1rem">✏️ Edit Page</div>
      <form method="POST">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:.8rem;margin-bottom:.8rem">
          <div>
            <label class="form-label">Page Title</label>
            <input class="form-input" type="text" name="title" value="{page['title']}" required>
          </div>
          <div>
            <label class="form-label">Icon (emoji)</label>
            <input class="form-input" type="text" name="icon" value="{page['icon']}" maxlength="4">
          </div>
          <div>
            <label class="form-label">Show in Sidebar</label>
            <select class="form-input" name="show_sidebar">
              <option value="1" {'selected' if page['show_sidebar'] else ''}>Yes</option>
              <option value="0" {'' if page['show_sidebar'] else 'selected'}>No</option>
            </select>
          </div>
          <div>
            <label class="form-label">URL</label>
            <div style="padding:.85rem 1rem;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);color:var(--text3);font-family:monospace">/page/{page['slug']}</div>
          </div>
        </div>
        <label class="form-label">Content</label>
        <textarea class="form-input" name="content" rows="10" required style="resize:vertical;margin-bottom:.8rem">{page['content']}</textarea>
        <button type="submit" class="btn btn-primary btn-sm">Save Changes</button>
      </form>
    </div>"""
    return admin_layout(f"Edit Page — {page['title']}", content_html, "pages")

# ═══════════════════════════════════════════════════════════════════
#   START
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    init_db()
    lan_ip = get_local_ip()
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║                NEXUS  –  Server started                   ║
╠═══════════════════════════════════════════════════════════╣
║  Local:        http://localhost:{PORT}                       ║
║  LAN:          http://{lan_ip}:{PORT}
║  Admin:        http://localhost:{PORT}/admin                 ║
║  Admin PW:     {ADMIN_PASSWORD}
╠═══════════════════════════════════════════════════════════╣
║  For internet access: deploy to Render.com                ║
║  See README.md for deployment guide                       ║
╚═══════════════════════════════════════════════════════════╝
    """)
    app.run(host=HOST, port=PORT, debug=DEBUG)
