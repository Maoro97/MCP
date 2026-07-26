# -*- coding: utf-8 -*-
"""
boi_rates.py — חיבור ישיר ל-API של בנק ישראל לשליפת שערי מטבע לפי תאריך.

משתמש ב-API החדש (EDGE / SDMX) של בנק ישראל:
  https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS/EXR/1.0/RER_<CUR>_ILS

הערה: יש להריץ ממחשב עם גישה לאינטרנט (הכלי רץ מקומית אצל המיישם). אם אין שער
לתאריך המבוקש (סופ"ש/חג) — נסוגים אחורה עד `lookback` ימים לשער הזמין האחרון.
"""

import json
import datetime as _dt
import urllib.request
import urllib.error

BOI_BASE = "https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS/EXR/1.0"


def _to_date(value):
    if isinstance(value, _dt.date):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"תאריך לא תקין: {value}")


def _extract_observation(data):
    """
    מחלץ את ערך השער מתוך תשובת SDMX-JSON של בנק ישראל, בצורה עמידה למבנה.
    מבנה טיפוסי: data.dataSets[0].series[k].observations[o] = [value, ...]
    """
    try:
        for ds in data.get("data", {}).get("dataSets", []):
            # תצפית ברמת dataSet
            for obs in (ds.get("observations") or {}).values():
                if obs and obs[0] is not None:
                    return float(obs[0])
            for series in (ds.get("series") or {}).values():
                for obs in (series.get("observations") or {}).values():
                    if obs and obs[0] is not None:
                        return float(obs[0])
    except (TypeError, ValueError, KeyError):
        pass
    return None


def get_rate(currency="USD", date=None, lookback=7, timeout=20):
    """
    מחזיר (שער, תאריך_בפועל) עבור המטבע לתאריך הנתון (מול השקל).
    אם אין שער בתאריך המדויק — נסוגים אחורה עד lookback ימים.
    מחזיר (None, None) אם לא נמצא / שגיאת רשת.
    """
    d = _to_date(date) if date else _dt.date.today()
    cur = str(currency).strip().upper()
    for back in range(lookback + 1):
        day = (d - _dt.timedelta(days=back)).strftime("%Y-%m-%d")
        url = f"{BOI_BASE}/RER_{cur}_ILS?startPeriod={day}&endPeriod={day}"
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.sdmx.data+json;version=1.0.0",
            "User-Agent": "priority-file-loader/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            continue
        rate = _extract_observation(data)
        if rate:
            return rate, day
    return None, None


def get_rates_for_dates(currency, dates, lookback=7):
    """שולף שערים למספר תאריכים (עם מטמון). מחזיר {date_str: (rate, effective_date)}."""
    cache = {}
    out = {}
    for dt in dates:
        key = _to_date(dt).strftime("%Y-%m-%d")
        if key not in cache:
            cache[key] = get_rate(currency, key, lookback=lookback)
        out[key] = cache[key]
    return out
