import os
import sqlite3
from flask import g

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "app.db")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=5)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8").read())
    seed_path = os.path.join(BASE_DIR, "seed.sql")
    if os.path.exists(seed_path):
        db.executescript(open(seed_path, encoding="utf-8").read())
    db.commit()
