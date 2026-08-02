# -*- coding: utf-8 -*-
"""
db.py — מסד נתונים (SQLite) להיסטוריית הטעינות.

שומר כל טעינה (מסך, קובץ מקור, כמויות, זמן, משתמש) ואת קובצי הפלט שנוצרו
(קובץ טעינה / פסולות / דוח) כ-BLOB, כדי שאפשר יהיה *לאחזר ולהוריד מחדש* טעינות
קודמות גם אחרי שהריצה פגה מהזיכרון או שהשרת הופעל מחדש.

מיקום הקובץ ניתן לדריסה ב-FILE_LOADER_DB. ברירת מחדל: ליד תיקיית הפלט
(output/loads.db) — נשמר לצמיתות בהרצה מקומית ו-Render עם דיסק קבוע. בסביבת
serverless (Vercel) המיקום ב-/tmp הוא זמני; לצורך שמירה קבועה שם הגדר
FILE_LOADER_DB לנתיב על אחסון קבוע.
"""
import os
import sqlite3
import datetime as _dt

_HERE = os.path.dirname(os.path.abspath(__file__))
_MAX_BLOB = 25 * 1024 * 1024   # תקרת גודל לקובץ שנשמר במסד (25MB)


def _base_dir():
    return os.environ.get("FILE_LOADER_OUTPUT") or (
        "/tmp/fl-output" if os.environ.get("VERCEL") else os.path.join(_HERE, "output"))


DB_PATH = os.environ.get("FILE_LOADER_DB") or os.path.join(_base_dir(), "loads.db")


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.Error:
        pass
    return conn


def init_db():
    """יוצר את הטבלאות (אם אינן קיימות) ומייבא היסטוריה ישנה מ-history.jsonl פעם אחת."""
    with _connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS loads(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT, screen TEXT, source TEXT,
          total INTEGER, valid INTEGER, invalid INTEGER, warnings INTEGER,
          via TEXT, run_id TEXT, has_rejected INTEGER, user TEXT
        );
        CREATE TABLE IF NOT EXISTS load_files(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          load_id INTEGER, name TEXT, label TEXT, kind TEXT, content BLOB,
          FOREIGN KEY(load_id) REFERENCES loads(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_loads_id ON loads(id DESC);
        CREATE INDEX IF NOT EXISTS idx_files_load ON load_files(load_id);
        """)
        empty = c.execute("SELECT COUNT(*) AS n FROM loads").fetchone()["n"] == 0
    if empty:
        _import_jsonl()


def _import_jsonl():
    """ייבוא חד-פעמי של רשומות מ-history.jsonl הישן (אם קיים), לשימור ההיסטוריה."""
    import json
    path = os.path.join(_base_dir(), "history.jsonl")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        add_load(json.loads(line))
                    except (ValueError, sqlite3.Error):
                        continue
    except OSError:
        pass


def add_load(entry):
    """מוסיף רשומת טעינה ומחזיר את המזהה (id). שקט בכל שגיאה (מחזיר None)."""
    entry = dict(entry)
    entry.setdefault("ts", _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    try:
        with _connect() as c:
            cur = c.execute(
                "INSERT INTO loads(ts,screen,source,total,valid,invalid,warnings,"
                "via,run_id,has_rejected,user) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (entry.get("ts"), entry.get("screen"), entry.get("source"),
                 int(entry.get("total") or 0), int(entry.get("valid") or 0),
                 int(entry.get("invalid") or 0), int(entry.get("warnings") or 0),
                 entry.get("via"), entry.get("run_id"),
                 1 if entry.get("has_rejected") else 0, entry.get("user") or ""))
            return cur.lastrowid
    except sqlite3.Error:
        return None


def add_file(load_id, name, label, kind, content):
    """שומר קובץ פלט (bytes) עבור טעינה. מדלג על קבצים גדולים מהתקרה."""
    if load_id is None or content is None or len(content) > _MAX_BLOB:
        return
    try:
        with _connect() as c:
            c.execute(
                "INSERT INTO load_files(load_id,name,label,kind,content) VALUES(?,?,?,?,?)",
                (load_id, name, label, kind, sqlite3.Binary(content)))
    except sqlite3.Error:
        pass


def list_loads(limit=200, screen=None):
    """רשומות הטעינה (חדשות ראשונות), כל אחת עם רשימת הקבצים המצורפים (מטא בלבד)."""
    try:
        with _connect() as c:
            q, args = "SELECT * FROM loads", []
            if screen:
                q += " WHERE screen=?"
                args.append(screen)
            q += " ORDER BY id DESC LIMIT ?"
            args.append(int(limit))
            loads = [dict(r) for r in c.execute(q, args).fetchall()]
            if loads:
                ids = [l["id"] for l in loads]
                files = {}
                rows = c.execute(
                    "SELECT id,load_id,name,label,kind FROM load_files WHERE load_id IN (%s)"
                    % ",".join("?" * len(ids)), ids).fetchall()
                for r in rows:
                    files.setdefault(r["load_id"], []).append(dict(r))
                for l in loads:
                    l["files"] = files.get(l["id"], [])
            return loads
    except sqlite3.Error:
        return []


def get_file(file_id):
    """מחזיר (שם, bytes) של קובץ שמור, או (None, None)."""
    try:
        with _connect() as c:
            r = c.execute("SELECT name,content FROM load_files WHERE id=?",
                          (int(file_id),)).fetchone()
            return (r["name"], bytes(r["content"])) if r else (None, None)
    except (sqlite3.Error, ValueError):
        return (None, None)


def distinct_screens():
    try:
        with _connect() as c:
            return [r["screen"] for r in c.execute(
                "SELECT DISTINCT screen FROM loads WHERE screen IS NOT NULL ORDER BY screen"
            ).fetchall()]
    except sqlite3.Error:
        return []


try:
    init_db()
except sqlite3.Error:
    pass
