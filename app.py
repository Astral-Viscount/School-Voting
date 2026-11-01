import os
import secrets
import sqlite3
from functools import wraps
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import (
    Flask, abort, g, jsonify, redirect, render_template, request,
    session, url_for, flash
)
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

load_dotenv(override=True)

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 8
app.config["SESSION_COOKIE_SECURE"] = os.getenv("COOKIE_SECURE") == "1"


if not app.config["SECRET_KEY"]:
    raise RuntimeError(
        "SECRET_KEY is missing."
    )


def env_set(name):
    values = os.getenv(name, "").split(",")
    return {value.strip().lower() for value in values if value.strip()}


ADMIN_EMAILS = env_set("ADMIN_EMAILS")
SCHOOL_DOMAINS = env_set("SCHOOL_DOMAIN")

DATABASE = "voting.db"
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

NZ_TIME = ZoneInfo("Pacific/Auckland")

def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def execute_db(query, args=()):
    db = get_db()
    db.execute(query, args)
    db.commit()


def now_nz():
    return datetime.now(NZ_TIME).replace(tzinfo=None)


def parse_date(value):
    if not value:
        return None

    for candidate in (value, value + ":00"):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue

    return None


def format_datetime(value):
    date_time = parse_date(value)

    if not date_time:
        return "not set"

    return date_time.strftime("%d %b %Y, %I:%M %p")


@app.template_filter("datetime")
def datetime_filter(value):
    return format_datetime(value)

@app.before_request
def csrf_protect():
    if request.method != "POST":
        return

    if request.endpoint == "login_data":
        return

    token = session.get("csrf_token")
    sent_token = (
        request.form.get("csrf_token")
        or request.headers.get("X-CSRFToken")
    )

    if not token or not sent_token or not secrets.compare_digest(token, sent_token):
        abort(403)


@app.context_processor
def inject_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)

    return {"csrf_token": session["csrf_token"]}


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), geolocation=()")

    return response


def verify_google_token(token):
    id_info = id_token.verify_oauth2_token(
        token,
        google_requests.Request(),
        GOOGLE_CLIENT_ID,
        clock_skew_in_seconds=10,
    )

    if not id_info.get("email_verified"):
        return None

    email = id_info["email"].lower()

    is_school_account = any(email.endswith(domain) for domain in SCHOOL_DOMAINS)
    is_allowlisted_admin = email in ADMIN_EMAILS

    if not (is_school_account or is_allowlisted_admin):
        return None

    return {
        "google_id": id_info["sub"],
        "email": email,
        "name": id_info.get("name", email.split("@")[0]),
        "should_be_admin": is_allowlisted_admin,
    }


@app.route("/login", methods=["POST"])
def login_data():
    payload = request.get_json(silent=True) or {}
    token = payload.get("credential")

    if not token:
        return jsonify({"error": "missing sign-in token."}), 400

    try:
        user_data = verify_google_token(token)
    except (ValueError, GoogleAuthError) as error:
        app.logger.warning("google token rejected: %s", error)
        return jsonify({"error": "sign-in failed. please try again."}), 401

    if user_data is None:
        return jsonify({"error": "unauthorized domain"}), 403

    user = query_db(
        "SELECT * FROM Users WHERE google_id=?",
        (user_data["google_id"],), one=True
    )

    if user is None:
        is_admin = 1 if user_data["should_be_admin"] else 0

        try:
            execute_db(
                "INSERT INTO Users (google_id, email, name, is_admin) "
                "VALUES (?, ?, ?, ?)",
                (user_data["google_id"], user_data["email"],
                 user_data["name"], is_admin)
            )
        except sqlite3.IntegrityError:
            pass

        user = query_db(
            "SELECT * FROM Users WHERE google_id=?",
            (user_data["google_id"],), one=True
        )

        if user is None:
            return jsonify({"error": "could not create your account."}), 500

    else:
        if user_data["should_be_admin"] and not user["is_admin"]:
            execute_db("UPDATE Users SET is_admin=1 WHERE id=?", (user["id"],))

        if user["name"] != user_data["name"]:
            execute_db(
                "UPDATE Users SET name=? WHERE id=?",
                (user_data["name"], user["id"])
            )

        user = query_db("SELECT * FROM Users WHERE id=?", (user["id"],), one=True)

    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["user_email"] = user["email"]
    session["user_name"] = user["name"]
    session["is_admin"] = bool(user["is_admin"])

    return jsonify({"success": True})


def get_current_user():
    if "user_id" not in session:
        return None

    if not hasattr(g, "current_user"):
        g.current_user = query_db(
            "SELECT * FROM Users WHERE id=?",
            (session["user_id"],), one=True
        )

    return g.current_user


def get_active_election():
    return query_db("SELECT * FROM Election WHERE is_active=1", one=True)


def voting_is_open(election):
    if not election or not election["is_active"]:
        return False, "there's no election running right now."

    now = now_nz()
    start = parse_date(election["start_date"])
    end = parse_date(election["end_date"])

    if start and now < start:
        return False, f"Voting starts {start.strftime('%d %b %Y, %I:%M %p')}."

    if end and now > end:
        return False, "Voting has closed for this election."

    return True, None
    

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login_page"))

        if get_current_user() is None:
            session.clear()
            return redirect(url_for("login_page"))

        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not get_current_user()["is_admin"]:
            abort(403)

        return view(*args, **kwargs)

    return wrapped


@app.route("/")
def home():
    return render_template("index.html", user=session.get("user_name"))


@app.route("/login")
def login_page():
    return render_template("login.html", client_id=GOOGLE_CLIENT_ID)


@app.route("/logout")
def logout():
    session.clear()
    flash("You've been signed out.", "info")

    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    if get_current_user()["is_admin"]:
        return redirect(url_for("admin_dashboard"))

    return redirect(url_for("voter_dashboard"))


@app.route("/voter")
@login_required
def voter_dashboard():
    return render_template("voter_dashboard.html", user=get_current_user())


@app.route("/admin")
@admin_required
def admin_dashboard():
    election = get_active_election() or query_db(
        "SELECT * FROM Election ORDER BY id DESC", one=True
    )

    stats = {
        "elections": query_db("SELECT COUNT(*) AS c FROM Election", one=True)["c"],
        "positions": 0,
        "users": query_db("SELECT COUNT(*) AS c FROM Users", one=True)["c"],
    }

    if election:
        stats["positions"] = query_db(
            "SELECT COUNT(*) AS c FROM Positions WHERE election_id=?",
            (election["id"],), one=True
        )["c"]

    return render_template(
        "admin_dashboard.html",
        user=get_current_user(), election=election, stats=stats
    )


def check_election_dates(start_date, end_date):
    start_dt = parse_date(start_date)
    end_dt = parse_date(end_date)

    if start_date and start_dt is None:
        return "The start date isn't valid."

    if end_date and end_dt is None:
        return "The end date isn't valid."

    if end_dt and end_dt <= now_nz():
        return "The end date/time must be in the future."

    if start_dt and end_dt and end_dt <= start_dt:
        return "The end date/time must be after the start date/time."

    return None


def get_election(election_id):
    return query_db(
        "SELECT * FROM Election WHERE id=?", (election_id,), one=True
    )


@app.route("/admin/elections", methods=["GET", "POST"])
@admin_required
def admin_elections():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "create":
            title = request.form.get("title", "").strip()[:100]
            description = request.form.get("description", "").strip()[:1000]
            start_date = request.form.get("start_date") or None
            end_date = request.form.get("end_date") or None

            if not title:
                error = "Please give the election a title."
            else:
                error = check_election_dates(start_date, end_date)

            if error:
                flash(error, "error")
            else:
                execute_db(
                    "INSERT INTO Election "
                    "(title, description, start_date, end_date, is_active) "
                    "VALUES (?, ?, ?, ?, 0)",
                    (title, description, start_date, end_date)
                )
                flash("Election created.", "success")
        
        elif action == "activate":
            election = get_election(request.form.get("election_id"))

            if election is None:
                flash("Election not found.", "error")
            else:
                end = parse_date(election["end_date"])

                if end and now_nz() > end:
                    flash(
                        f"Can't activate '{election['title']}': its end time "
                        "has already passed. Create a new election instead.",
                        "error"
                    )
                else:
                    execute_db(
                        "UPDATE Election "
                        "SET is_active = CASE WHEN id=? THEN 1 ELSE 0 END",
                        (election["id"],)
                    )
                    flash(
                        f"'{election['title']}' is now live. Any other "
                        "election was switched off.", "success"
                    )

        elif action == "deactivate":
            election = get_election(request.form.get("election_id"))

            if election is None:
                flash("Election not found.", "error")
            else:
                execute_db(
                    "UPDATE Election SET is_active=0 WHERE id=?",
                    (election["id"],)
                )
                flash(f"'{election['title']}' has been deactivated.", "info")

        return redirect(url_for("admin_elections"))

    elections = query_db("SELECT * FROM Election ORDER BY id DESC")

    return render_template("admin_elections.html", elections=elections)


@app.route("/admin/positions", methods=["GET", "POST"])
@admin_required
def admin_positions():
    election_id = request.values.get("election_id", type=int)

    if request.method == "POST":
        action = request.form.get("action")

        if get_election(election_id) is None:
            flash("Please choose an election first.", "error")
            return redirect(url_for("admin_positions"))

        if action == "create":
            position_name = request.form.get("position_name", "").strip()[:100]

            try:
                max_votes = int(request.form.get("max_votes", 1))
            except ValueError:
                max_votes = 1

            max_votes = max(1, min(max_votes, 10))

            duplicate = query_db(
                "SELECT id FROM Positions "
                "WHERE election_id=? AND LOWER(position_name)=LOWER(?)",
                (election_id, position_name), one=True
            )

            if not position_name:
                flash("Please enter a position name.", "error")
            elif duplicate:
                flash(f"'{position_name}' already exists in this election.", "error")
            else:
                execute_db(
                    "INSERT INTO Positions (election_id, position_name, max_votes) "
                    "VALUES (?, ?, ?)",
                    (election_id, position_name, max_votes)
                )
                flash("Position added.", "success")

        elif action == "delete":
            position_id = request.form.get("position_id", type=int)

            execute_db(
                "DELETE FROM Positions WHERE id=? AND election_id=?",
                (position_id, election_id)
            )
            flash("Position removed.", "info")

        return redirect(url_for("admin_positions", election_id=election_id))

    elections = query_db("SELECT * FROM Election ORDER BY id DESC")
    positions = []

    if election_id:
        positions = query_db(
            "SELECT * FROM Positions WHERE election_id=? ORDER BY id",
            (election_id,)
        )

    return render_template(
        "admin_positions.html",
        elections=elections, positions=positions, election_id=election_id
    )


@app.errorhandler(403)
def forbidden(error):
    return render_template("403.html"), 403


@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


@app.errorhandler(405)
def method_not_allowed(error):
    return render_template("405.html"), 405


@app.errorhandler(500)
def internal_error(error):
    db = getattr(g, "_database", None)
    if db is not None:
        db.rollback()

    return render_template("500.html"), 500


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


#Debugging
#Testing routes and errors
@app.route("/test")
def test():
    raise RuntimeError("test")


#should return 200 if ok
@app.route("/health")
def health():
    try:
        query_db("SELECT 1", one=True)
    except sqlite3.Error:
        return jsonify({"status": "error"}), 503

    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True)