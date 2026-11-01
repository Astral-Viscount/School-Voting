import os
import sqlite3
from datetime import datetime

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("SCHOOL_DOMAIN", "@example.com")
os.environ.setdefault("ADMIN_EMAILS", "admin@example.com")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")

import app as app_module

SCHEMA = """
CREATE TABLE Users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    google_id TEXT UNIQUE,
    email TEXT UNIQUE,
    name TEXT,
    is_admin INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE Election(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    start_date TEXT,
    end_date TEXT,
    is_active INTEGER DEFAULT 0
);
CREATE TABLE Positions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    election_id INTEGER NOT NULL,
    position_name TEXT NOT NULL,
    max_votes INTEGER DEFAULT 1,
    FOREIGN KEY(election_id) REFERENCES Election(id)
);
"""

ADMIN_ID = 1
STUDENT_ID = 2


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test.db")

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO Users (google_id, email, name, is_admin) "
        "VALUES ('g1', 'admin@example.com', 'Admin', 1)"
    )
    conn.execute(
        "INSERT INTO Users (google_id, email, name, is_admin) "
        "VALUES ('g2', 'student@example.com', 'Student', 0)"
    )
    conn.commit()
    conn.close()

    app_module.DATABASE = db_path
    app_module.app.config["TESTING"] = True
    app_module.app.config["SESSION_COOKIE_SECURE"] = False

    with app_module.app.test_client() as test_client:
        yield test_client


def login_as(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Test"


def post_form(client, path, data):
    with client.session_transaction() as sess:
        sess["csrf_token"] = "tok"

    payload = {"csrf_token": "tok"}
    payload.update(data)

    return client.post(path, data=payload)


def db_rows(sql, args=()):
    conn = sqlite3.connect(app_module.DATABASE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, args).fetchall()
    conn.close()

    return rows


def db_run(sql, args=()):
    conn = sqlite3.connect(app_module.DATABASE)
    cursor = conn.execute(sql, args)
    conn.commit()
    last_id = cursor.lastrowid
    conn.close()

    return last_id


def add_election(title="Test Election", start=None, end="2099-01-01T00:00", active=0):
    return db_run(
        "INSERT INTO Election (title, start_date, end_date, is_active) "
        "VALUES (?, ?, ?, ?)",
        (title, start, end, active)
    )


def test_parse_date_handles_form_values():
    assert app_module.parse_date("2026-11-02T09:00") == datetime(2026, 11, 2, 9, 0)


def test_parse_date_returns_none_for_empty_or_invalid():
    assert app_module.parse_date("") is None
    assert app_module.parse_date(None) is None
    assert app_module.parse_date("not a date") is None


def test_format_datetime():
    assert app_module.format_datetime("2026-11-02T09:00") == "02 Nov 2026, 09:00 AM"
    assert app_module.format_datetime(None) == "Not set"


@pytest.fixture
def at_noon(monkeypatch):
    monkeypatch.setattr(app_module, "now_nz", lambda: datetime(2026, 10, 30, 12, 0))


def election(start, end, active=1):
    return {"is_active": active, "start_date": start, "end_date": end}


def test_no_election_means_closed():
    is_open, message = app_module.voting_is_open(None)

    assert is_open is False
    assert "no election" in message.lower()


def test_inactive_election_is_closed(at_noon):
    is_open, _ = app_module.voting_is_open(election("2026-10-01T00:00", "2026-12-01T00:00", active=0))

    assert is_open is False


def test_before_start_is_closed_and_says_when(at_noon):
    is_open, message = app_module.voting_is_open(election("2026-11-01T09:00", "2026-11-08T09:00"))

    assert is_open is False
    assert "starts" in message.lower()


def test_after_end_is_closed(at_noon):
    is_open, message = app_module.voting_is_open(election("2026-10-01T09:00", "2026-10-20T09:00"))

    assert is_open is False
    assert "closed" in message.lower()


def test_inside_window_is_open(at_noon):
    is_open, message = app_module.voting_is_open(election("2026-10-01T09:00", "2026-11-20T09:00"))

    assert is_open is True
    assert message is None