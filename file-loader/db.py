# -*- coding: utf-8 -*-
"""
db.py — מסד נתונים להיסטוריית הטעינות, עם שני מנועים:

  • Postgres  — כאשר מוגדר משתנה סביבה DATABASE_URL / POSTGRES_URL
                (למשל Vercel Postgres / Neon). שמירה קבועה גם ב-serverless.
  • SQLite    — ברירת מחדל (מקומי / Render עם דיסק קבוע). קובץ output/loads.db,
                ניתן לדריסה ב-FILE_LOADER_DB.

שומר כל טעינה (מסך, קובץ מקור, כמויות, זמן, משתמש) ואת קובצי הפלט שנוצרו
(טעינה / פסולות / דוח) כ-BLOB, כדי שאפשר יהיה *לאחזר ולהוריד מחדש* טעינות קודמות.
"""
import os
import contextlib
import datetime as _dt

_HERE = os.path.dirname(os.path.abspath(__file__))
_MAX_BLOB = 25 * 1024 * 1024   # תקרת גודל לקובץ שנשמר במסד (25MB)


def _pg_url():
    """מחזיר את מחרוזת החיבור ל-Postgres אם הוגדרה (מעדיף חיבור ישיר, לא-pooled)."""
    for k in ("DATABASE_URL", "POSTGRES_URL_NON_POOLING", "POSTGRES_URL"):
        v = os.environ.get(k)
        if v:
            return v.strip()
    return None


_PG_URL = _pg_url()
IS_PG = bool(_PG_URL)
PH = "%s" if IS_PG else "?"           # תו ה-placeholder לפי המנוע
_BLOB_COL = "BYTEA" if IS_PG else "BLOB"
_ID_COL = "BIGSERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"


def _base_dir():
    return os.environ.get("FILE_LOADER_OUTPUT") or (
        "/tmp/fl-output" if os.environ.get("VERCEL") else os.path.join(_HERE, "output"))


DB_PATH = os.environ.get("FILE_LOADER_DB") or os.path.join(_base_dir(), "loads.db")


def _raw_connect():
    if IS_PG:
        import psycopg2
        return psycopg2.connect(_PG_URL)
    import sqlite3
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    return conn


@contextlib.contextmanager
def _conn():
    """חיבור עם commit/rollback וסגירה, לשני המנועים."""
    conn = _raw_connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _cursor(conn):
    if IS_PG:
        import psycopg2.extras
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()


def _binary(content):
    if IS_PG:
        import psycopg2
        return psycopg2.Binary(content)
    import sqlite3
    return sqlite3.Binary(content)


def init_db():
    """יוצר את הטבלאות (idempotent) ומייבא היסטוריה ישנה מ-history.jsonl פעם אחת."""
    with _conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            "CREATE TABLE IF NOT EXISTS loads("
            f"  id {_ID_COL},"
            "  ts TEXT, screen TEXT, source TEXT,"
            "  total INTEGER, valid INTEGER, invalid INTEGER, warnings INTEGER,"
            "  via TEXT, run_id TEXT, has_rejected INTEGER, \"user\" TEXT)")
        cur.execute(
            "CREATE TABLE IF NOT EXISTS load_files("
            f"  id {_ID_COL},"
            "  load_id INTEGER, name TEXT, label TEXT, kind TEXT,"
            f"  content {_BLOB_COL})")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_files_load ON load_files(load_id)")
        cur.execute("SELECT COUNT(*) AS n FROM loads")
        empty = cur.fetchone()["n"] == 0
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
                    except Exception:  # noqa: BLE001
                        continue
    except OSError:
        pass


def add_load(entry):
    """מוסיף רשומת טעינה ומחזיר את המזהה (id). שקט בכל שגיאה (מחזיר None)."""
    entry = dict(entry)
    entry.setdefault("ts", _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    cols = ("ts", "screen", "source", "total", "valid", "invalid", "warnings",
            "via", "run_id", "has_rejected", "user")
    vals = (entry.get("ts"), entry.get("screen"), entry.get("source"),
            int(entry.get("total") or 0), int(entry.get("valid") or 0),
            int(entry.get("invalid") or 0), int(entry.get("warnings") or 0),
            entry.get("via"), entry.get("run_id"),
            1 if entry.get("has_rejected") else 0, entry.get("user") or "")
    names = ",".join(f'"{c}"' if c == "user" else c for c in cols)
    marks = ",".join([PH] * len(cols))
    try:
        with _conn() as conn:
            cur = _cursor(conn)
            if IS_PG:
                cur.execute(f"INSERT INTO loads({names}) VALUES({marks}) RETURNING id", vals)
                return cur.fetchone()["id"]
            cur.execute(f"INSERT INTO loads({names}) VALUES({marks})", vals)
            return cur.lastrowid
    except Exception:  # noqa: BLE001
        return None


def upsert_load(entry):
    """כמו add_load, אך אם כבר קיימת רשומה לאותו (מסך + קובץ מקור) — מעדכן אותה
    (ומוחק את הקבצים הישנים שלה) במקום ליצור חדשה. מחזיר את מזהה הרשומה."""
    entry = dict(entry)
    entry.setdefault("ts", _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    source = entry.get("source")
    if source:
        try:
            with _conn() as conn:
                cur = _cursor(conn)
                cur.execute(f"SELECT id FROM loads WHERE screen={PH} AND source={PH} "
                            f"ORDER BY id DESC LIMIT 1", (entry.get("screen"), source))
                r = cur.fetchone()
                if r:
                    lid = r["id"]
                    cur.execute(
                        f"UPDATE loads SET ts={PH},total={PH},valid={PH},invalid={PH},"
                        f"warnings={PH},via={PH},run_id={PH},has_rejected={PH},\"user\"={PH} "
                        f"WHERE id={PH}",
                        (entry.get("ts"), int(entry.get("total") or 0), int(entry.get("valid") or 0),
                         int(entry.get("invalid") or 0), int(entry.get("warnings") or 0),
                         entry.get("via"), entry.get("run_id"),
                         1 if entry.get("has_rejected") else 0, entry.get("user") or "", lid))
                    cur.execute(f"DELETE FROM load_files WHERE load_id={PH}", (lid,))
                    return lid
        except Exception:  # noqa: BLE001
            pass
    return add_load(entry)


def delete_load(load_id):
    """מוחק רשומת טעינה מההיסטוריה ואת הקבצים שלה. מחזיר True בהצלחה."""
    try:
        with _conn() as conn:
            cur = _cursor(conn)
            cur.execute(f"DELETE FROM load_files WHERE load_id={PH}", (int(load_id),))
            cur.execute(f"DELETE FROM loads WHERE id={PH}", (int(load_id),))
        return True
    except Exception:  # noqa: BLE001
        return False


def add_file(load_id, name, label, kind, content):
    """שומר קובץ פלט (bytes) עבור טעינה. מדלג על קבצים גדולים מהתקרה."""
    if load_id is None or content is None or len(content) > _MAX_BLOB:
        return
    try:
        with _conn() as conn:
            _cursor(conn).execute(
                f"INSERT INTO load_files(load_id,name,label,kind,content) "
                f"VALUES({PH},{PH},{PH},{PH},{PH})",
                (load_id, name, label, kind, _binary(content)))
    except Exception:  # noqa: BLE001
        pass


def list_loads(limit=200, screen=None):
    """רשומות הטעינה (חדשות ראשונות), כל אחת עם רשימת הקבצים המצורפים (מטא בלבד)."""
    try:
        with _conn() as conn:
            cur = _cursor(conn)
            q, args = "SELECT * FROM loads", []
            if screen:
                q += f" WHERE screen={PH}"
                args.append(screen)
            q += f" ORDER BY id DESC LIMIT {PH}"
            args.append(int(limit))
            cur.execute(q, args)
            loads = [dict(r) for r in cur.fetchall()]
            if loads:
                ids = [l["id"] for l in loads]
                marks = ",".join([PH] * len(ids))
                cur.execute(
                    f"SELECT id,load_id,name,label,kind FROM load_files "
                    f"WHERE load_id IN ({marks})", ids)
                files, snap = {}, set()
                for r in cur.fetchall():
                    if r["kind"] == "snapshot":     # תמונת-מצב לפתיחה מחדש — לא קובץ להורדה
                        snap.add(r["load_id"])
                    else:
                        files.setdefault(r["load_id"], []).append(dict(r))
                for l in loads:
                    l["files"] = files.get(l["id"], [])
                    l["has_snapshot"] = l["id"] in snap
            return loads
    except Exception:  # noqa: BLE001
        return []


def get_file(file_id):
    """מחזיר (שם, bytes) של קובץ שמור, או (None, None)."""
    try:
        with _conn() as conn:
            cur = _cursor(conn)
            cur.execute(f"SELECT name,content FROM load_files WHERE id={PH}", (int(file_id),))
            r = cur.fetchone()
            return (r["name"], bytes(r["content"])) if r else (None, None)
    except Exception:  # noqa: BLE001
        return (None, None)


def status():
    """מצב המסד לתצוגה/אבחון: איזה מנוע, האם נגיש, ומספר רשומות."""
    info = {"backend": "postgres" if IS_PG else "sqlite",
            "vercel": bool(os.environ.get("VERCEL")), "ok": False, "error": "", "count": 0}
    try:
        with _conn() as conn:
            cur = _cursor(conn)
            cur.execute("SELECT COUNT(*) AS n FROM loads")
            info["count"] = cur.fetchone()["n"]
        info["ok"] = True
    except Exception as e:  # noqa: BLE001
        info["error"] = str(e)[:200]
    return info


def get_snapshot(load_id):
    """מחזיר את תמונת-המצב (JSON bytes) של טעינה לפתיחה מחדש, או None."""
    try:
        with _conn() as conn:
            cur = _cursor(conn)
            cur.execute(f"SELECT content FROM load_files WHERE load_id={PH} "
                        f"AND kind='snapshot' ORDER BY id DESC LIMIT 1", (int(load_id),))
            r = cur.fetchone()
            return bytes(r["content"]) if r else None
    except (Exception,):  # noqa: BLE001
        return None


def distinct_screens():
    try:
        with _conn() as conn:
            cur = _cursor(conn)
            cur.execute("SELECT DISTINCT screen FROM loads "
                        "WHERE screen IS NOT NULL ORDER BY screen")
            return [r["screen"] for r in cur.fetchall()]
    except Exception:  # noqa: BLE001
        return []


try:
    init_db()
except Exception:  # noqa: BLE001
    pass
