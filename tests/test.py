import os
import sqlite3

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
)
"""

ADMIN_ID = 1
STUDENT_ID = 2


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test.db")

    conn = sqlite3.connect(db_path)
    conn.execute(SCHEMA)
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


def test_home_page_loads(client):
    assert client.get("/").status_code == 200


def test_unknown_page_is_404(client):
    assert client.get("/definitely-not-a-page").status_code == 404


def test_voter_page_requires_login(client):
    response = client.get("/voter")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_ghost_session_is_sent_to_login(client):
    login_as(client, 999)
    response = client.get("/voter")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_student_cannot_open_admin(client):
    login_as(client, STUDENT_ID)

    assert client.get("/admin").status_code == 403


def test_admin_can_open_admin(client):
    login_as(client, ADMIN_ID)

    assert client.get("/admin").status_code == 200


def test_dashboard_routes_by_role(client):
    login_as(client, ADMIN_ID)
    assert client.get("/dashboard").headers["Location"].endswith("/admin")

    login_as(client, STUDENT_ID)
    assert client.get("/dashboard").headers["Location"].endswith("/voter")


def test_post_without_csrf_token_is_rejected(client):
    login_as(client, STUDENT_ID)

    assert client.post("/dashboard").status_code == 403


def test_post_with_valid_csrf_token_passes_the_check(client):
    login_as(client, STUDENT_ID)

    with client.session_transaction() as sess:
        sess["csrf_token"] = "abc123"

    response = client.post("/dashboard", headers={"X-CSRFToken": "abc123"})

    assert response.status_code == 405


def test_security_headers_are_present(client):
    response = client.get("/")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "Referrer-Policy" in response.headers


def test_wrong_method_shows_405_page(client):
    login_as(client, STUDENT_ID)

    with client.session_transaction() as sess:
        sess["csrf_token"] = "abc123"

    response = client.post("/dashboard", headers={"X-CSRFToken": "abc123"})

    assert response.status_code == 405
    assert "405" in response.get_data(as_text=True)


def test_logout_shows_message(client):
    login_as(client, STUDENT_ID)
    response = client.get("/logout", follow_redirects=True)

    assert "signed out" in response.get_data(as_text=True)


def test_health_check_is_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}