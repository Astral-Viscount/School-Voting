""

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
        "SECRET_KEY is missing. Run `python utils/secret_token.py` "
        "and add the output to your .env file."
    )


def env_set(name):
    return {
        item.strip().lower()
        for item in os.getenv(name, "").split(",")
        if item.strip()
    }


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

if __name__ == "__main__":
    app.run(debug=True)