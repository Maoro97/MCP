#!/usr/bin/env python3
"""מדפיס תיק 360° מ-stdin (פלט GET /v1/clients/:id/portfolio).

תצוגת CLI לאימות מהיר של ה-API בלי להריץ את ה-Frontend.
"""

from __future__ import annotations

import json
import sys

ICON = {"critical": "⚠", "warning": "⚠", "info": "ℹ"}
GROUPS = (("pension", "פנסיוני"), ("financial", "פיננסי"), ("other", "אחר"))


def money(v: float | None) -> str:
    return f"₪{v:,.0f}" if v is not None else "— לא התקבל"


def pct(v: float | None) -> str:
    return f"{v:g}%" if v is not None else "— לא התקבל"


def main() -> int:
    p = json.load(sys.stdin)
    if "client" not in p:
        print("  שגיאה:", p.get("message", p))
        return 1

    c, s = p["client"], p["summary"]
    as_of = p["dataAsOf"] or "—"
    completeness = s["dataCompleteness"]

    print(
        f"   {c['firstName']} {c['lastName']} · ת.ז ****{c['nationalIdLast4']} · "
        f"בן/בת {c['age']} · נכון ל-{as_of}"
    )
    print(
        f"   צבירה: {money(s['totalBalance'])} | "
        f"ד\"נ צבירה: {pct(s['feeOnBalanceWeighted'])} | "
        f"א.כ.ע חודשי: {money(s['disabilityMonthly'])} | "
        f"שלמות נתונים: {completeness:.0%}"
    )
    if s["productsWithoutBalance"]:
        print(f"   ⚠ {s['productsWithoutBalance']} מוצרים ללא יתרה מדווחת")

    for key, label in GROUPS:
        for x in p["groups"][key]:
            lock = " 🔒 מקדם קצבה מובטח" if x["hasGuaranteedAnnuityFactor"] else ""
            dormant = " (לא פעיל)" if x["isDormant"] else ""
            print(
                f"   · [{label}] {x['productTypeHe']} · {x['providerName']} · "
                f"{x['policyNumber']}{dormant}{lock}"
            )
            print(
                f"       {money(x['totalBalance'])} | "
                f"ד\"נ הפקדה {pct(x['feeOnDepositPct'])} | "
                f"ד\"נ צבירה {pct(x['feeOnBalancePct'])} | "
                f"שלמות {x['dataCompleteness']:.0%}"
            )
            # ה-provenance שמאחורי המספר — מה שנדרש להציג בביקורת
            src = x["sources"].get("fee_on_balance_pct")
            if src and src["raw"] is not None:
                fixes = f", תיקונים: {','.join(src['fixes'])}" if src["fixes"] else ""
                print(
                    f"       ↳ מקור ד\"נ צבירה: {src['providerName']} · "
                    f"ערך גולמי '{src['raw']}' · ביטחון {src['confidence']:.0%}{fixes}"
                )

    print(f"   הערות ({len(p['advisories'])}):")
    for a in p["advisories"][:8]:
        print(f"     {ICON.get(a['severity'], '·')} {a['message']}")

    print(f"   חריגים פתוחים: {len(p['openIssues'])}")
    for issue in p["openIssues"][:4]:
        print(f"     ✖ {issue['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
