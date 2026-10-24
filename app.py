import os
import secrets
import sqlite3
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask, abort, g, jsonify, redirect, render_template, request,
    session, url_for
)
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

load_dotenv(override=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

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
    return render_template("admin_dashboard.html", user=get_current_user())


@app.errorhandler(403)
def forbidden(error):
    return render_template("403.html"), 403


@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(debug=True)