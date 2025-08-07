"""SQLite helper minimal (logs + paquets)."""
import sqlite3
from pathlib import Path
import datetime
from .config import settings

DB_PATH = Path(settings.DATABASE_URL.replace("sqlite:///", ""))


def _conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              timestamp TEXT,
              log TEXT
            );
            CREATE TABLE IF NOT EXISTS network_requests (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              timestamp TEXT,
              ip TEXT,
              verdict TEXT,
              summary TEXT
            );
            """
        )


def save_log(msg: str):
    with _conn() as c:
        c.execute(
            "INSERT INTO logs(timestamp, log) VALUES (?,?)",
            (datetime.datetime.now().isoformat(timespec="seconds"), msg),
        )


def save_network_packet(ip: str, verdict: str, summary: str):
    with _conn() as c:
        c.execute(
            "INSERT INTO network_requests(timestamp, ip, verdict, summary) VALUES (?,?,?,?)",
            (datetime.datetime.now().isoformat(timespec="seconds"), ip, verdict, summary),
        )
