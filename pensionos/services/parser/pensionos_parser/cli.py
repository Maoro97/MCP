"""CLI לפיתוח ולבדיקת מיפויים.

    python -m pensionos_parser fixtures/clean_menora.xml
    python -m pensionos_parser --json fixtures/*.xml > out.json

מציג את הפלט בעברית כדי שאנליסט דומיין יוכל לאמת מיפוי בלי לקרוא JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import ParseResult
from .pipeline import parse_file

_SEV_ICON = {"info": "ℹ", "warning": "⚠", "error": "✖", "blocker": "🛑"}
_STATUS_HE = {
    "succeeded": "פוענח במלואו",
    "partial": "פוענח חלקית",
    "no_data": "היצרן דיווח שאין מידע",
    "failed": "כשל",
    "quarantined": "הועבר להסגר",
}


def _fmt_money(value: float | None) -> str:
    return f"₪{value:,.0f}" if value is not None else "— לא התקבל"


def _fmt_pct(value: float | None) -> str:
    return f"{value:g}%" if value is not None else "— לא התקבל"


def render(result: ParseResult, path: str) -> str:
    lines: list[str] = []
    lines.append(f"\n{'=' * 72}")
    lines.append(f"קובץ: {Path(path).name}")
    lines.append(
        f"סטטוס: {_STATUS_HE.get(result.status, result.status)}  |  "
        f"מיפוי: {result.mapping_version}  |  "
        f"תקן: {result.standard_version}  |  "
        f"{result.stats.duration_ms}ms"
    )
    if result.sanitize_report.fixes:
        lines.append(f"תיקוני קליטה: {', '.join(result.sanitize_report.fixes)}")
    if result.subject:
        s = result.subject
        lines.append(f"לקוח: {s.first_name or ''} {s.last_name or ''} · ת.ז {s.national_id}")
    lines.append("-" * 72)

    for p in result.products:
        flag = " 🔒 מקדם קצבה מובטח" if p.has_guaranteed_annuity_factor else ""
        dormant = " (לא פעיל)" if p.is_dormant else ""
        lines.append(
            f"· {p.product_type} · {p.provider_name or p.provider_code} · "
            f"{p.policy_number}{dormant}{flag}"
        )
        lines.append(
            f"    צבירה: {_fmt_money(p.total_balance)} | "
            f"ד\"נ הפקדה: {_fmt_pct(p.fee_on_deposit_pct)} | "
            f"ד\"נ צבירה: {_fmt_pct(p.fee_on_balance_pct)} | "
            f"שלמות: {p.data_completeness:.0%}"
        )
        for cov in p.coverages:
            lines.append(
                f"      כיסוי {cov.coverage_type}: "
                f"{_fmt_money(cov.sum_insured or cov.monthly_benefit)}"
            )

    if result.issues:
        lines.append("-" * 72)
        lines.append(f"חריגים ({len(result.issues)}):")
        for issue in result.issues:
            icon = _SEV_ICON.get(issue.severity, "·")
            ref = f" [{issue.entity_ref}]" if issue.entity_ref else ""
            lines.append(f"  {icon} {issue.message_he}{ref}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pensionos_parser", description="פענוח קבצי מסלקה")
    ap.add_argument("paths", nargs="+", help="נתיבי קבצי XML")
    ap.add_argument("--json", action="store_true", help="פלט JSON גולמי")
    args = ap.parse_args(argv)

    results = []
    for path in args.paths:
        result = parse_file(path)
        results.append(result)
        if not args.json:
            print(render(result, path))

    if args.json:
        print(
            json.dumps(
                [r.model_dump(mode="json") for r in results],
                ensure_ascii=False,
                indent=2,
            )
        )

    # קוד יציאה שימושי ל-CI: 1 אם קובץ כלשהו לא נקלט
    return 0 if all(r.is_usable for r in results) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
