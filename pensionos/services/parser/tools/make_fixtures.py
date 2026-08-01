#!/usr/bin/env python3
"""מחולל קורפוס קבצי מסלקה — תקינים ופגומים.

זהו גם ה-Mock של המסלקה לצורכי פיתוח: הוא מייצר בדיוק את סוגי הקבצים
שראינו בשטח, כולל התקלות. מריצים:

    python tools/make_fixtures.py

⚠️ הנתונים סינתטיים לחלוטין. תעודות הזהות תקינות מבחינת ספרת ביקורת אך
   אינן שייכות לאדם אמיתי — אין להשתמש בקורפוס בסביבת ייצור.
"""

from __future__ import annotations

import sys
import zlib
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# ת"ז סינתטיות שעוברות ולידציית ספרת ביקורת
CLIENT_ID = "039472519"
OTHER_ID = "021234562"


def _header(provider_code: str = "520023185", provider_name: str = "מנורה מבטחים") -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Mimshak>
  <GIRSAT-MIVNE-ACHID>2.9</GIRSAT-MIVNE-ACHID>
  <YeshutYatzran>
    <KOD-MEZAHE-YATZRAN>{provider_code}</KOD-MEZAHE-YATZRAN>
    <SHEM-YATZRAN>{provider_name}</SHEM-YATZRAN>
  </YeshutYatzran>
  <Mutzarim>
    <Mutzar>
      <YeshutLakoach>
        <MISPAR-ZIHUY-LAKOACH>{{national_id}}</MISPAR-ZIHUY-LAKOACH>
        <SHEM-PRATI>דנה</SHEM-PRATI>
        <SHEM-MISHPACHA>כהן</SHEM-MISHPACHA>
        <TAARICH-LEIDA>19840317</TAARICH-LEIDA>
      </YeshutLakoach>
      <HeshbonotOPolisot>"""


_FOOTER = """      </HeshbonotOPolisot>
    </Mutzar>
  </Mutzarim>
</Mimshak>
"""


def _account(
    policy: str = "5512340",
    sug: str = "1",
    balance: str = "842100.55",
    fee_deposit: str = "1.49",
    fee_balance: str = "0.22",
    join: str = "20090601",
    status: str = "1",
    report: str = "20260312",
    extra: str = "",
    with_coverage: bool = True,
    with_beneficiary: bool = True,
) -> str:
    coverage = (
        """
          <PirteiKisuiim>
            <PirteiKisuy>
              <KOD-SUG-KISUY>1</KOD-SUG-KISUY>
              <SHEM-KISUY>אובדן כושר עבודה</SHEM-KISUY>
              <SCHUM-KITZBA-CHODSHIT>9400</SCHUM-KITZBA-CHODSHIT>
              <ALUT-KISUY-CHODSHI>112.5</ALUT-KISUY-CHODSHI>
              <TKUFAT-ACHSHARA-CHODASHIM>3</TKUFAT-ACHSHARA-CHODASHIM>
            </PirteiKisuy>
            <PirteiKisuy>
              <KOD-SUG-KISUY>2</KOD-SUG-KISUY>
              <SHEM-KISUY>שאירים</SHEM-KISUY>
              <SCHUM-KITZBA-CHODSHIT>6200</SCHUM-KITZBA-CHODSHIT>
              <ALUT-KISUY-CHODSHI>78</ALUT-KISUY-CHODSHI>
            </PirteiKisuy>
          </PirteiKisuiim>"""
        if with_coverage
        else ""
    )
    beneficiary = (
        """
          <Mutavim>
            <Mutav>
              <SHEM-MUTAV>יוסי כהן</SHEM-MUTAV>
              <KIRVA-MISHPACHTIT>1</KIRVA-MISHPACHTIT>
              <ACHUZ-ZAKAUT>100</ACHUZ-ZAKAUT>
              <TAARICH-IDKUN>20180204</TAARICH-IDKUN>
            </Mutav>
          </Mutavim>"""
        if with_beneficiary
        else ""
    )
    return f"""
        <HeshbonOPolisa>
          <MISPAR-POLISA-O-HESHBON>{policy}</MISPAR-POLISA-O-HESHBON>
          <SUG-MUTZAR>{sug}</SUG-MUTZAR>
          <SHEM-TOCHNIT>מסלול כללי</SHEM-TOCHNIT>
          <SHEM-MAASIK>אלפא טכנולוגיות בע"מ</SHEM-MAASIK>
          <TAARICH-HITZTARFUT-MUTZAR>{join}</TAARICH-HITZTARFUT-MUTZAR>
          <STATUS-POLISA-O-CHESHBON>{status}</STATUS-POLISA-O-CHESHBON>
          <PirteiMaslulHashkaa>
            <KOD-MASLUL-HASHKAA>2001</KOD-MASLUL-HASHKAA>
            <SHEM-MASLUL-HASHKAA>מסלול תלוי גיל</SHEM-MASLUL-HASHKAA>
          </PirteiMaslulHashkaa>
          <NetuneiMutzar>
            <TAARICH-NECHONUT>{report}</TAARICH-NECHONUT>
            <TOTAL-CHISACHON-MTZBR>{balance}</TOTAL-CHISACHON-MTZBR>
            <TOTAL-CHISACHON-MTZBR-TAGMULIM-OVED>310400</TOTAL-CHISACHON-MTZBR-TAGMULIM-OVED>
            <TOTAL-CHISACHON-MTZBR-TAGMULIM-MAAVID>402300.55</TOTAL-CHISACHON-MTZBR-TAGMULIM-MAAVID>
            <TOTAL-CHISACHON-MTZBR-PITZUIM>129400</TOTAL-CHISACHON-MTZBR-PITZUIM>
            <SHEUR-TSUA-NETO>6.31</SHEUR-TSUA-NETO>
            <SHEUR-DMEI-NIHUL-ME-HAFKADA>{fee_deposit}</SHEUR-DMEI-NIHUL-ME-HAFKADA>
            <SHEUR-DMEI-NIHUL-ME-HATZVIRA>{fee_balance}</SHEUR-DMEI-NIHUL-ME-HATZVIRA>{extra}
          </NetuneiMutzar>{coverage}{beneficiary}
        </HeshbonOPolisa>"""


def _doc(accounts: str, national_id: str = CLIENT_ID, **hdr: str) -> str:
    return _header(**hdr).format(national_id=national_id) + accounts + _FOOTER


# --------------------------------------------------------------------------
# הקורפוס
# --------------------------------------------------------------------------


def build() -> dict[str, bytes]:
    out: dict[str, bytes] = {}

    # 1. קובץ תקין — שני חשבונות, אחד מהם עם מקדם קצבה מובטח
    clean = _doc(
        _account()
        + _account(
            policy="8871200",
            sug="6",
            balance="310500",
            fee_deposit="4.00",
            fee_balance="1.05",
            join="20090101",
            extra="""
            <KIYUM-MEKADEM-MUVTACH>1</KIYUM-MEKADEM-MUVTACH>
            <MEKADEM-KITZBA-MUVTACH>167.4</MEKADEM-KITZBA-MUVTACH>
            <TAARICH-SIYUM-HATAVAT-DMEI-NIHUL>20261231</TAARICH-SIYUM-HATAVAT-DMEI-NIHUL>""",
        )
    )
    out["01_clean_menora.xml"] = clean.encode("utf-8")

    # 2. מצהיר UTF-8, בפועל windows-1255 — התקלה מס' 1 בשטח
    out["02_cp1255_mislabeled.xml"] = clean.encode("cp1255", errors="replace")

    # 3. BOM כפול + תווי בקרה + סימני כיווניות בשמות
    dirty = clean.replace("<SHEM-PRATI>דנה</SHEM-PRATI>", "<SHEM-PRATI>‏דנה‎</SHEM-PRATI>")
    dirty = dirty.replace("מנורה מבטחים", "מנורה\x00 מבטחים\x1f")
    out["03_bom_control_bidi.xml"] = b"\xef\xbb\xbf\xef\xbb\xbf" + dirty.encode("utf-8")

    # 4. תגים ריקים, אפסים שמשמעם "לא ידוע", ותאריך אפס
    empties = _doc(
        _account(
            fee_deposit="0",
            fee_balance="",
            report="00000000",
            balance="",
            with_coverage=False,
        )
    )
    out["04_empty_tags_and_zeros.xml"] = empties.encode("utf-8")

    # 5. פורמטים מעוותים: מפריד אלפים, מינוס עוקב, פסיק עשרוני, תאריך DD/MM/YYYY
    messy = _doc(
        _account(
            balance="1,284,300.75",
            fee_deposit="1,49",
            fee_balance="0.0035",  # שבר עשרוני במקום אחוז
            report="12/03/2026",
            join="01.06.2009",
        ).replace(
            "<SHEUR-TSUA-NETO>6.31</SHEUR-TSUA-NETO>",
            "<SHEUR-TSUA-NETO>3.20-</SHEUR-TSUA-NETO>",  # מינוס עוקב
        )
    )
    out["05_messy_numbers_dates.xml"] = messy.encode("utf-8")

    # 6. הורדה שנקטעה באמצע
    out["06_truncated.xml"] = clean[: int(len(clean) * 0.62)].encode("utf-8")

    # 7. XXE — ניסיון קריאת קובץ מקומי
    xxe = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!DOCTYPE Mimshak [\n"
        '  <!ENTITY xxe SYSTEM "file:///etc/passwd">\n'
        "]>\n"
        + _doc(
            _account(extra="\n            <SHEM-YATZRAN>&xxe;</SHEM-YATZRAN>")
        ).split("\n", 1)[1]
    )
    out["07_xxe_attack.xml"] = xxe.encode("utf-8")

    # 8. Billion Laughs
    lols = "\n".join(
        f'  <!ENTITY lol{i} "&lol{i - 1};&lol{i - 1};&lol{i - 1};&lol{i - 1};'
        f'&lol{i - 1};&lol{i - 1};&lol{i - 1};&lol{i - 1};&lol{i - 1};&lol{i - 1};">'
        for i in range(1, 10)
    )
    bomb = (
        '<?xml version="1.0"?>\n<!DOCTYPE Mimshak [\n'
        '  <!ENTITY lol "lol">\n' + lols + "\n]>\n"
        "<Mimshak><GIRSAT-MIVNE-ACHID>2.9</GIRSAT-MIVNE-ACHID>"
        "<YeshutYatzran><KOD-MEZAHE-YATZRAN>520023185</KOD-MEZAHE-YATZRAN>"
        "<SHEM-YATZRAN>&lol9;</SHEM-YATZRAN></YeshutYatzran></Mimshak>"
    )
    out["08_billion_laughs.xml"] = bomb.encode("utf-8")

    # 9. ת"ז שאינה של הלקוח שביקשנו — אירוע אבטחה
    out["09_subject_mismatch.xml"] = _doc(_account(), national_id=OTHER_ID).encode("utf-8")

    # 10. היצרן מדווח שאין מידע
    nodata = _doc("\n        <EIN-MEIDA>1</EIN-MEIDA>", **{"provider_name": "הפניקס"})
    out["10_no_data.xml"] = nodata.encode("utf-8")

    # 11. אותו חשבון פעמיים, עם תאריכי נכונות שונים
    dup = _doc(
        _account(report="20251130", balance="800000")
        + _account(report="20260312", balance="842100.55")
    )
    out["11_duplicate_accounts.xml"] = dup.encode("utf-8")

    # 12. יצרן עם סטייה מהתקן — דורש דריסת מיפוי
    quirk = _doc(
        _account(fee_balance="").replace(
            "<SHEUR-DMEI-NIHUL-ME-HATZVIRA></SHEUR-DMEI-NIHUL-ME-HATZVIRA>",
            "</NetuneiMutzar>\n          <DmeiNihulMeyuchadim>"
            "<SHEUR-TZVIRA>0.0035</SHEUR-TZVIRA></DmeiNihulMeyuchadim>\n"
            "          <NetuneiMutzar>",
        ),
        provider_code="999999999",
        provider_name="בית השקעות אלפא",
    )
    out["12_provider_quirk.xml"] = quirk.encode("utf-8")

    # 13. קוד סוג מוצר לא מוכר
    out["13_unknown_product_type.xml"] = _doc(_account(sug="99")).encode("utf-8")

    # 14. גרסת מבנה אחיד שאין לה מיפוי
    out["14_unknown_standard.xml"] = clean.replace(
        "<GIRSAT-MIVNE-ACHID>2.9</GIRSAT-MIVNE-ACHID>",
        "<GIRSAT-MIVNE-ACHID>9.9</GIRSAT-MIVNE-ACHID>",
    ).encode("utf-8")

    # 15. קובץ גדול — 400 חשבונות, לבדיקת streaming
    out["15_large.xml"] = _doc(
        "".join(_account(policy=f"90{i:05d}") for i in range(400))
    ).encode("utf-8")

    return out


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    files = build()
    for name, data in sorted(files.items()):
        (FIXTURES / name).write_bytes(data)
        print(f"  {name:34s} {len(data):>9,} bytes  crc={zlib.crc32(data):08x}")
    print(f"\n{len(files)} fixtures → {FIXTURES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
