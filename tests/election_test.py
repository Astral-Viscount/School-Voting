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
    

def test_student_cannot_open_admin_pages(client):
    login_as(client, STUDENT_ID)

    assert client.get("/admin/elections").status_code == 403
    assert client.get("/admin/positions").status_code == 403


def test_student_cannot_create_an_election(client):
    login_as(client, STUDENT_ID)
    post_form(client, "/admin/elections", {"action": "create", "title": "Sneaky"})

    assert db_rows("SELECT * FROM Election") == []


def test_admin_dashboard_shows_the_election(client):
    add_election("Spring Prefects")
    login_as(client, ADMIN_ID)

    html = client.get("/admin").get_data(as_text=True)

    assert "Spring Prefects" in html


def test_admin_can_create_an_election(client):
    login_as(client, ADMIN_ID)
    post_form(client, "/admin/elections", {
        "action": "create", "title": "Spring Prefects",
        "start_date": "2099-01-01T09:00", "end_date": "2099-01-08T15:00",
    })

    rows = db_rows("SELECT * FROM Election")

    assert len(rows) == 1
    assert rows[0]["title"] == "Spring Prefects"
    assert rows[0]["is_active"] == 0


def test_blank_title_is_rejected(client):
    login_as(client, ADMIN_ID)
    post_form(client, "/admin/elections", {"action": "create", "title": "   "})

    assert db_rows("SELECT * FROM Election") == []


def test_end_date_in_the_past_is_rejected(client):
    login_as(client, ADMIN_ID)
    post_form(client, "/admin/elections", {
        "action": "create", "title": "Old", "end_date": "2000-01-01T10:00",
    })

    assert db_rows("SELECT * FROM Election") == []


def test_end_before_start_is_rejected(client):
    login_as(client, ADMIN_ID)
    post_form(client, "/admin/elections", {
        "action": "create", "title": "Backwards",
        "start_date": "2099-01-02T10:00", "end_date": "2099-01-01T10:00",
    })

    assert db_rows("SELECT * FROM Election") == []


def active_ids():
    return [row["id"] for row in db_rows("SELECT id FROM Election WHERE is_active=1")]


def test_only_one_election_can_be_active(client):
    first = add_election("A")
    second = add_election("B")
    login_as(client, ADMIN_ID)

    post_form(client, "/admin/elections", {"action": "activate", "election_id": first})
    assert active_ids() == [first]

    post_form(client, "/admin/elections", {"action": "activate", "election_id": second})
    assert active_ids() == [second]


def test_cannot_activate_an_ended_election(client):
    old = add_election("Old", end="2000-01-01T00:00")
    login_as(client, ADMIN_ID)
    post_form(client, "/admin/elections", {"action": "activate", "election_id": old})

    assert active_ids() == []


def test_deactivate_turns_it_off(client):
    live = add_election("Live", active=1)
    login_as(client, ADMIN_ID)
    post_form(client, "/admin/elections", {"action": "deactivate", "election_id": live})

    assert active_ids() == []


def position_names(election_id):
    rows = db_rows(
        "SELECT position_name FROM Positions WHERE election_id=? ORDER BY id",
        (election_id,)
    )
    return [row["position_name"] for row in rows]


def test_admin_can_add_a_position(client):
    election_id = add_election()
    login_as(client, ADMIN_ID)
    post_form(client, "/admin/positions", {
        "action": "create", "election_id": election_id,
        "position_name": "Head Prefect", "max_votes": "1",
    })

    assert position_names(election_id) == ["Head Prefect"]


def test_blank_and_duplicate_positions_are_rejected(client):
    election_id = add_election()
    login_as(client, ADMIN_ID)

    for name in ["Head Prefect", "", "head prefect"]:
        post_form(client, "/admin/positions", {
            "action": "create", "election_id": election_id, "position_name": name,
        })

    assert position_names(election_id) == ["Head Prefect"]


def test_max_votes_is_clamped(client):
    election_id = add_election()
    login_as(client, ADMIN_ID)
    post_form(client, "/admin/positions", {
        "action": "create", "election_id": election_id,
        "position_name": "Big", "max_votes": "999",
    })

    assert db_rows("SELECT max_votes FROM Positions")[0]["max_votes"] == 10


def test_admin_can_delete_a_position(client):
    election_id = add_election()
    position_id = db_run(
        "INSERT INTO Positions (election_id, position_name) VALUES (?, 'Temp')",
        (election_id,)
    )
    login_as(client, ADMIN_ID)
    post_form(client, "/admin/positions", {
        "action": "delete", "election_id": election_id, "position_id": position_id,
    })

    assert position_names(election_id) == []


def test_cannot_delete_a_position_through_another_election(client):
    election_a = add_election("A")
    election_b = add_election("B")
    position_id = db_run(
        "INSERT INTO Positions (election_id, position_name) VALUES (?, 'Keep me')",
        (election_a,)
    )
    login_as(client, ADMIN_ID)
    post_form(client, "/admin/positions", {
        "action": "delete", "election_id": election_b, "position_id": position_id,
    })

    assert position_names(election_a) == ["Keep me"]


def test_voter_sees_no_election_message(client):
    login_as(client, STUDENT_ID)
    html = client.get("/voter").get_data(as_text=True)

    assert "no active election" in html.lower()


def test_voter_sees_open_election_and_positions(client):
    election_id = add_election(
        "Spring Prefects", start="2000-01-01T00:00", end="2099-01-01T00:00", active=1
    )
    db_run(
        "INSERT INTO Positions (election_id, position_name) VALUES (?, 'Head Prefect')",
        (election_id,)
    )
    login_as(client, STUDENT_ID)
    html = client.get("/voter").get_data(as_text=True)

    assert "Spring Prefects" in html
    assert "voting is open" in html
    assert "Head Prefect" in html


def test_voter_is_told_when_voting_starts(client):
    add_election("Future", start="2099-01-01T09:00", end="2099-01-08T09:00", active=1)
    login_as(client, STUDENT_ID)
    html = client.get("/voter").get_data(as_text=True)

    assert "Voting starts" in html


def add_user(name, email=None, is_admin=0):
    email = email or f"{name.lower().replace(' ', '.')}@example.com"

    return db_run(
        "INSERT INTO Users (google_id, email, name, is_admin) VALUES (?, ?, ?, ?)",
        (f"g-{email}", email, name, is_admin)
    )


def add_position(election_id, name="Head Prefect"):
    return db_run(
        "INSERT INTO Positions (election_id, position_name) VALUES (?, ?)",
        (election_id, name)
    )


def add_candidate(position_id, name="Candidate One", bio="Vote for me"):
    user_id = add_user(name)
    candidate_id = db_run(
        "INSERT INTO Candidates (position_id, user_id, bio) VALUES (?, ?, ?)",
        (position_id, user_id, bio)
    )

    return candidate_id, user_id


def live_race():
    election_id = add_election(
        "Live", start="2000-01-01T00:00", end="2099-01-01T00:00", active=1
    )
    position_id = add_position(election_id)
    candidate_id, _ = add_candidate(position_id)

    return election_id, position_id, candidate_id


def vote(client, position_id, candidate_id):
    return post_form(client, f"/vote/{position_id}/{candidate_id}", {})


def vote_rows():
    return db_rows("SELECT * FROM Votes")


def test_student_can_vote(client):
    _, position_id, candidate_id = live_race()
    login_as(client, STUDENT_ID)

    response = vote(client, position_id, candidate_id)

    assert response.status_code == 200
    assert response.get_json() == {"success": True}

    rows = vote_rows()

    assert len(rows) == 1
    assert rows[0]["voter_id"] == STUDENT_ID
    assert rows[0]["candidate_id"] == candidate_id


def test_cannot_vote_twice_for_the_same_position(client):
    _, position_id, candidate_id = live_race()
    login_as(client, STUDENT_ID)

    vote(client, position_id, candidate_id)
    second = vote(client, position_id, candidate_id)

    assert second.status_code == 409
    assert len(vote_rows()) == 1


def test_cannot_switch_to_another_candidate_after_voting(client):
    _, position_id, first = live_race()
    second, _ = add_candidate(position_id, "Candidate Two")
    login_as(client, STUDENT_ID)

    vote(client, position_id, first)
    response = vote(client, position_id, second)

    assert response.status_code == 409
    assert vote_rows()[0]["candidate_id"] == first


def test_can_vote_once_in_each_position(client):
    election_id, position_a, candidate_a = live_race()
    position_b = add_position(election_id, "Sports Captain")
    candidate_b, _ = add_candidate(position_b, "Sporty Person")
    login_as(client, STUDENT_ID)

    vote(client, position_a, candidate_a)
    vote(client, position_b, candidate_b)

    assert len(vote_rows()) == 2


def test_two_students_can_vote_for_the_same_candidate(client):
    _, position_id, candidate_id = live_race()
    other_student = add_user("Other Student")

    login_as(client, STUDENT_ID)
    vote(client, position_id, candidate_id)

    login_as(client, other_student)
    vote(client, position_id, candidate_id)

    assert len(vote_rows()) == 2


def test_cannot_vote_when_no_election_is_live(client):
    election_id = add_election("Not live", active=0)
    position_id = add_position(election_id)
    candidate_id, _ = add_candidate(position_id)
    login_as(client, STUDENT_ID)

    assert vote(client, position_id, candidate_id).status_code == 403
    assert vote_rows() == []


def test_cannot_vote_after_the_end_time(client):
    election_id = add_election("Over", start=None, end="2000-01-08T09:00", active=1)
    position_id = add_position(election_id)
    candidate_id, _ = add_candidate(position_id)
    login_as(client, STUDENT_ID)

    response = vote(client, position_id, candidate_id)

    assert response.status_code == 403
    assert "closed" in response.get_json()["error"].lower()
    assert vote_rows() == []


def test_cannot_vote_before_the_start_time(client):
    election_id = add_election("Later", start="2099-01-01T09:00", end="2099-01-08T09:00", active=1)
    position_id = add_position(election_id)
    candidate_id, _ = add_candidate(position_id)
    login_as(client, STUDENT_ID)

    assert vote(client, position_id, candidate_id).status_code == 403
    assert vote_rows() == []


def test_candidate_from_another_position_is_rejected(client):
    election_id, position_a, _ = live_race()
    position_b = add_position(election_id, "Sports Captain")
    candidate_b, _ = add_candidate(position_b, "Sporty Person")
    login_as(client, STUDENT_ID)

    assert vote(client, position_a, candidate_b).status_code == 400
    assert vote_rows() == []


def test_position_from_a_non_live_election_is_rejected(client):
    live_race()
    other_election = add_election("Other", active=0)
    other_position = add_position(other_election)
    other_candidate, _ = add_candidate(other_position, "Elsewhere Person")
    login_as(client, STUDENT_ID)

    assert vote(client, other_position, other_candidate).status_code == 400
    assert vote_rows() == []


def test_vote_without_a_csrf_token_is_rejected(client):
    _, position_id, candidate_id = live_race()
    login_as(client, STUDENT_ID)

    assert client.post(f"/vote/{position_id}/{candidate_id}").status_code == 403
    assert vote_rows() == []


def test_logged_out_user_cannot_vote(client):
    _, position_id, candidate_id = live_race()
    response = vote(client, position_id, candidate_id)

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert vote_rows() == []


def test_admin_cannot_vote(client):
    _, position_id, candidate_id = live_race()
    login_as(client, ADMIN_ID)

    assert vote(client, position_id, candidate_id).status_code == 403
    assert vote_rows() == []


def test_admin_cannot_open_the_voter_dashboard(client):
    login_as(client, ADMIN_ID)

    assert client.get("/voter").status_code == 403


def test_voter_dashboard_lists_candidates_with_vote_buttons(client):
    live_race()
    login_as(client, STUDENT_ID)
    html = client.get("/voter").get_data(as_text=True)

    assert "Candidate One" in html
    assert "Vote for me" in html
    assert "vote-btn" in html


def test_voter_dashboard_shows_voted_state(client):
    _, position_id, candidate_id = live_race()
    login_as(client, STUDENT_ID)
    vote(client, position_id, candidate_id)

    html = client.get("/voter").get_data(as_text=True)

    assert "You&#39;ve voted for this position" in html or "You've voted for this position" in html
    assert "vote-btn" not in html


def test_position_without_candidates_says_so(client):
    election_id = add_election("Live", start="2000-01-01T00:00", end="2099-01-01T00:00", active=1)
    add_position(election_id)
    login_as(client, STUDENT_ID)
    html = client.get("/voter").get_data(as_text=True)

    assert "No candidates have been added" in html


def assign(client, election_id, email, position_id, bio=""):
    return post_form(client, "/admin/candidates", {
        "action": "assign", "election_id": election_id,
        "student_email": email, "position_id": position_id, "bio": bio,
    })


def candidate_count():
    return len(db_rows("SELECT * FROM Candidates"))


def test_admin_can_add_a_candidate_with_a_description(client):
    election_id = add_election("E")
    position_id = add_position(election_id)
    login_as(client, ADMIN_ID)
    assign(client, election_id, "student@example.com", position_id, "I love this school")

    rows = db_rows("SELECT * FROM Candidates")

    assert len(rows) == 1
    assert rows[0]["user_id"] == STUDENT_ID
    assert rows[0]["bio"] == "I love this school"


def test_email_lookup_ignores_case_and_spaces(client):
    election_id = add_election("E")
    position_id = add_position(election_id)
    login_as(client, ADMIN_ID)
    assign(client, election_id, "  STUDENT@Example.com ", position_id)

    assert candidate_count() == 1


def test_cannot_add_someone_who_has_not_signed_in(client):
    election_id = add_election("E")
    position_id = add_position(election_id)
    login_as(client, ADMIN_ID)
    assign(client, election_id, "nobody@example.com", position_id)

    assert candidate_count() == 0


def test_cannot_add_an_admin_as_a_candidate(client):
    election_id = add_election("E")
    position_id = add_position(election_id)
    login_as(client, ADMIN_ID)
    assign(client, election_id, "admin@example.com", position_id)

    assert candidate_count() == 0


def test_student_can_only_stand_for_one_position_per_election(client):
    election_id = add_election("E")
    head = add_position(election_id, "Head Prefect")
    sports = add_position(election_id, "Sports Captain")
    login_as(client, ADMIN_ID)

    assign(client, election_id, "student@example.com", head)
    assign(client, election_id, "student@example.com", sports)

    assert candidate_count() == 1


def test_cannot_add_a_candidate_to_a_position_from_another_election(client):
    election_a = add_election("A")
    election_b = add_election("B")
    position_in_b = add_position(election_b)
    login_as(client, ADMIN_ID)
    assign(client, election_a, "student@example.com", position_in_b)

    assert candidate_count() == 0


def test_admin_can_remove_a_candidate_without_votes(client):
    election_id = add_election("E")
    position_id = add_position(election_id)
    candidate_id, _ = add_candidate(position_id)
    login_as(client, ADMIN_ID)
    post_form(client, "/admin/candidates", {
        "action": "remove", "election_id": election_id, "candidate_id": candidate_id,
    })

    assert candidate_count() == 0


def test_cannot_remove_a_candidate_who_has_votes(client):
    election_id, position_id, candidate_id = live_race()
    login_as(client, STUDENT_ID)
    vote(client, position_id, candidate_id)

    login_as(client, ADMIN_ID)
    post_form(client, "/admin/candidates", {
        "action": "remove", "election_id": election_id, "candidate_id": candidate_id,
    })

    assert candidate_count() == 1


def test_removing_a_position_removes_its_candidates(client):
    election_id = add_election("E")
    position_id = add_position(election_id)
    add_candidate(position_id)
    login_as(client, ADMIN_ID)
    post_form(client, "/admin/positions", {
        "action": "delete", "election_id": election_id, "position_id": position_id,
    })

    assert candidate_count() == 0
    assert position_names(election_id) == []


def test_cannot_remove_a_position_that_has_votes(client):
    election_id, position_id, candidate_id = live_race()
    login_as(client, STUDENT_ID)
    vote(client, position_id, candidate_id)

    login_as(client, ADMIN_ID)
    post_form(client, "/admin/positions", {
        "action": "delete", "election_id": election_id, "position_id": position_id,
    })

    assert position_names(election_id) == ["Head Prefect"]
    assert len(vote_rows()) == 1


def test_student_cannot_use_the_candidates_page(client):
    election_id = add_election("E")
    position_id = add_position(election_id)
    login_as(client, STUDENT_ID)

    assert client.get("/admin/candidates").status_code == 403

    assign(client, election_id, "student@example.com", position_id)

    assert candidate_count() == 0