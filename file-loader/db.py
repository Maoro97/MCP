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
            "  ts TEXT, screen TEXT, source TEXT, name TEXT, client TEXT, status TEXT,"
            "  total INTEGER, valid INTEGER, invalid INTEGER, warnings INTEGER,"
            "  via TEXT, run_id TEXT, has_rejected INTEGER, \"user\" TEXT)")
        # מיגרציה למסדים ותיקים: הוספת עמודות שנוספו לאורך הדרך (idempotent)
        for _col in ("name TEXT", "client TEXT", "status TEXT"):
            try:
                cur.execute(f"ALTER TABLE loads ADD COLUMN {_col}")
            except Exception:  # noqa: BLE001 — כבר קיימת
                pass
        # נירמול ל-'' כדי שקיבוץ/השוואה יעבדו בלי טיפול ב-NULL
        for _c in ("name", "client", "status"):
            try:
                cur.execute(f"UPDATE loads SET {_c}='' WHERE {_c} IS NULL")
            except Exception:  # noqa: BLE001
                pass
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
    cols = ("ts", "screen", "source", "name", "client", "status",
            "total", "valid", "invalid", "warnings",
            "via", "run_id", "has_rejected", "user")
    vals = (entry.get("ts"), entry.get("screen"), entry.get("source"),
            (entry.get("name") or "").strip(), (entry.get("client") or "").strip(),
            (entry.get("status") or "").strip(),
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


def add_version(entry):
    """שומר טעינה כ*גרסה חדשה* בלוג השינויים. כל שמירה מוסיפה גרסה (append-only) —
    הזהות ("קובץ") נגזרת מהצירוף (מסך + מזהה/שם + לקוח), וכל הגרסאות של אותו צירוף
    מקובצות יחד במסך ההיסטוריה. אם קיימת כבר גרסה עם סטטוס עבודה — הוא נשמר לגרסה
    החדשה כדי לא לאבד אותו. מחזיר את מזהה הגרסה."""
    entry = dict(entry)
    name = (entry.get("name") or "").strip()
    client = (entry.get("client") or "").strip()
    if not entry.get("status"):   # ירושת סטטוס העבודה מהגרסה האחרונה של אותו קובץ
        try:
            with _conn() as conn:
                cur = _cursor(conn)
                cur.execute(
                    f"SELECT status FROM loads WHERE screen={PH} AND name={PH} AND client={PH} "
                    f"AND status<>'' ORDER BY id DESC LIMIT 1",
                    (entry.get("screen"), name, client))
                r = cur.fetchone()
                if r and r["status"]:
                    entry["status"] = r["status"]
        except Exception:  # noqa: BLE001
            pass
    return add_load(entry)


# תאימות לאחור: הקוד הישן קרא ל-upsert_load; כעת כל שמירה = גרסה חדשה.
upsert_load = add_version


def delete_load(load_id):
    """מוחק גרסה בודדת מלוג השינויים ואת הקבצים שלה. מחזיר True בהצלחה."""
    try:
        with _conn() as conn:
            cur = _cursor(conn)
            cur.execute(f"DELETE FROM load_files WHERE load_id={PH}", (int(load_id),))
            cur.execute(f"DELETE FROM loads WHERE id={PH}", (int(load_id),))
        return True
    except Exception:  # noqa: BLE001
        return False


def _group_where(screen, name, client):
    """תנאי WHERE + ערכים לזיהוי "קובץ" (קבוצת גרסאות)."""
    return (f"screen={PH} AND name={PH} AND client={PH}",
            (screen, (name or "").strip(), (client or "").strip()))


def delete_group(screen, name, client):
    """מוחק את כל הגרסאות של קובץ (צירוף מסך+מזהה+לקוח) ואת קבציהן. מחזיר True."""
    try:
        cond, args = _group_where(screen, name, client)
        with _conn() as conn:
            cur = _cursor(conn)
            cur.execute(f"SELECT id FROM loads WHERE {cond}", args)
            ids = [r["id"] for r in cur.fetchall()]
            for lid in ids:
                cur.execute(f"DELETE FROM load_files WHERE load_id={PH}", (lid,))
            cur.execute(f"DELETE FROM loads WHERE {cond}", args)
        return True
    except Exception:  # noqa: BLE001
        return False


def set_status(screen, name, client, status):
    """מעדכן את סטטוס העבודה (טיוטה/מוכן/נטען) לכל גרסאות הקובץ. מחזיר True."""
    try:
        cond, args = _group_where(screen, name, client)
        with _conn() as conn:
            _cursor(conn).execute(
                f"UPDATE loads SET status={PH} WHERE {cond}", ((status or "").strip(), *args))
        return True
    except Exception:  # noqa: BLE001
        return False


def rename_group(screen, name, client, new_name=None, new_client=None):
    """משנה את המזהה/הלקוח של כל גרסאות הקובץ. מחזיר True."""
    try:
        cond, args = _group_where(screen, name, client)
        sets, vals = [], []
        if new_name is not None:
            sets.append(f"name={PH}"); vals.append((new_name or "").strip())
        if new_client is not None:
            sets.append(f"client={PH}"); vals.append((new_client or "").strip())
        if not sets:
            return True
        with _conn() as conn:
            _cursor(conn).execute(
                f"UPDATE loads SET {','.join(sets)} WHERE {cond}", (*vals, *args))
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


def list_load_groups(limit=300, screen=None):
    """מחזיר את היסטוריית הטעינות מקובצת ל"קבצים" (אב→בן): כל קובץ הוא צירוף
    (מסך + מזהה/שם + לקוח), ותחתיו רשימת הגרסאות (חדשות→ישנות) עם דלתא מול
    הגרסה הקודמת. שורת האב מציגה את הגרסה האחרונה (head)."""
    rows = list_loads(limit=max(int(limit) * 6, 600), screen=screen)
    groups, order = {}, []
    for r in rows:                       # rows כבר ממוינות id יורד (חדש→ישן)
        key = (r.get("screen") or "", (r.get("name") or ""), (r.get("client") or ""))
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "key": "␟".join(key),
                "screen": key[0], "name": key[1], "client": key[2],
                "status": r.get("status") or "", "versions": [],
            }
            order.append(key)
        g["versions"].append(r)          # יורד: [0]=החדשה ביותר
        if r.get("status"):
            g["status"] = g["status"] or r["status"]

    out = []
    for key in order:
        g = groups[key]
        vs = g["versions"]
        head = vs[0]
        # דלתא לכל גרסה מול הגרסה שאחריה (הישנה יותר)
        for i, v in enumerate(vs):
            prev = vs[i + 1] if i + 1 < len(vs) else None
            if prev is None:
                v["delta"] = None        # הגרסה הראשונה — אין מול מה להשוות
            else:
                v["delta"] = {
                    "valid": (v.get("valid") or 0) - (prev.get("valid") or 0),
                    "invalid": (v.get("invalid") or 0) - (prev.get("invalid") or 0),
                    "warnings": (v.get("warnings") or 0) - (prev.get("warnings") or 0),
                    "total": (v.get("total") or 0) - (prev.get("total") or 0),
                }
        g.update({
            "version_count": len(vs),
            "head": head,
            "ts": head.get("ts"), "user": head.get("user"),
            "source": head.get("source"), "total": head.get("total"),
            "valid": head.get("valid"), "invalid": head.get("invalid"),
            "warnings": head.get("warnings"),
        })
        out.append(g)
    out.sort(key=lambda x: (x["head"]["id"]), reverse=True)   # קובץ אחרון-נגע ראשון
    return out[:int(limit)]


def stats(screen=None):
    """מדדי-על להיסטוריה: כמה קבצים, כמה גרסאות/טעינות, סה"כ שורות תקינות שנטענו,
    ואחוז הצלחה ממוצע (לפי הגרסה האחרונה של כל קובץ)."""
    groups = list_load_groups(limit=100000, screen=screen)
    files_n = len(groups)
    versions_n = sum(g["version_count"] for g in groups)
    valid_rows = sum((g["head"].get("valid") or 0) for g in groups)
    rates = []
    for g in groups:
        h = g["head"]
        tot = (h.get("valid") or 0) + (h.get("invalid") or 0)
        if tot:
            rates.append((h.get("valid") or 0) / tot)
    success = round(100 * sum(rates) / len(rates)) if rates else 0
    return {"files": files_n, "versions": versions_n,
            "valid_rows": valid_rows, "success": success}


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
