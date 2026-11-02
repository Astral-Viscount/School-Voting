import sqlite3

conn = sqlite3.connect("voting.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS Users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    google_id TEXT UNIQUE,
    email TEXT UNIQUE,
    name TEXT,
    is_admin INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS Election(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    start_date TEXT,
    end_date TEXT,
    is_active INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS Positions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    election_id INTEGER NOT NULL,
    position_name TEXT NOT NULL,
    max_votes INTEGER DEFAULT 1,
    FOREIGN KEY(election_id) REFERENCES Election(id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS Candidates(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    bio TEXT DEFAULT '',
    photo TEXT DEFAULT '{}',
    UNIQUE(position_id, user_id),
    FOREIGN KEY(position_id) REFERENCES Positions(id),
    FOREIGN KEY(user_id) REFERENCES Users(id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS Votes(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    voter_id INTEGER NOT NULL,
    position_id INTEGER NOT NULL,
    candidate_id INTEGER NOT NULL,
    time TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(voter_id, position_id),
    FOREIGN KEY(voter_id) REFERENCES Users(id),
    FOREIGN KEY(position_id) REFERENCES Positions(id),
    FOREIGN KEY(candidate_id) REFERENCES Candidates(id)
)
""")

conn.commit()
conn.close()