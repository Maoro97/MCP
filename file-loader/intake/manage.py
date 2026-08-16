# -*- coding: utf-8 -*-
"""
manage.py — ניהול משתמשי ממשק הקליטה מהטרמינל

לשימוש כשאין דרך להיכנס דרך הדפדפן: שכחתם סיסמה, החשבון ננעל, או שצריך
לפתוח משתמש ראשון בשרת מרוחק. הפעולות זהות למסך "משתמשים" בממשק.

    python -m intake.manage list                 רשימת המשתמשים
    python -m intake.manage passwd <שם משתמש>    איפוס סיסמה (גם משחרר נעילה)
    python -m intake.manage create <שם משתמש>    יצירת משתמש
    python -m intake.manage unlock <שם משתמש>    שחרור חשבון נעול/חסום
    python -m intake.manage phone <שם> <טלפון>   עדכון הטלפון לקודי אימות

דגלים ל-create:  --admin  --phone 0501234567  --name "שם לתצוגה"

הסיסמה נקראת בהקלדה מוסתרת ואינה נשמרת בהיסטוריית הפקודות.
הרצה מתוך תיקיית file-loader, כדי שיימצא אותו מסד נתונים שהשרת משתמש בו.
"""

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intake import security, store  # noqa: E402


def _ask_password(username):
    """קורא סיסמה פעמיים ומוודא שהיא עומדת במדיניות."""
    while True:
        first = getpass.getpass(f"סיסמה חדשה ל-{username}: ")
        problem = security.password_problem(first)
        if problem:
            print(f"  ✗ {problem}")
            continue
        if first != getpass.getpass("שוב, לאימות: "):
            print("  ✗ הסיסמאות אינן זהות")
            continue
        return first


def cmd_list(_args):
    users = store.list_users()
    if not users:
        print("אין משתמשים. פתחו את /intake/ בדפדפן להקמה ראשונית, "
              "או הריצו:  python -m intake.manage create <שם> --admin")
        return 0
    print(f"{'משתמש':<20} {'הרשאה':<8} {'טלפון':<16} {'מצב':<8} כניסה אחרונה")
    print("-" * 76)
    for user in users:
        state = "פעיל" if user["active"] else "חסום"
        if user["locked_until"]:
            state = "נעול"
        print(f"{user['username']:<20} {user['role']:<8} "
              f"{user['phone'] or '—':<16} {state:<8} {user['last_login'] or '—'}")
    return 0


def cmd_create(args):
    if store.get_user(args.username):
        print(f"✗ המשתמש '{args.username}' כבר קיים. לאיפוס סיסמה: "
              f"python -m intake.manage passwd {args.username}")
        return 1
    password = _ask_password(args.username)
    store.create_user(username=args.username, password=password,
                      display_name=args.name or args.username,
                      phone=args.phone or "",
                      role="admin" if args.admin else "user")
    print(f"✓ נוצר משתמש '{args.username}'"
          f"{' (מנהל)' if args.admin else ''}.")
    if not args.phone:
        print("  ⚠ לא הוגדר טלפון — בלעדיו אי אפשר לקבל קודי אימות. "
              f"עדכנו:  python -m intake.manage phone {args.username} 0501234567")
    return 0


def _require(username):
    user = store.get_user(username)
    if not user:
        print(f"✗ לא נמצא משתמש '{username}'. לרשימה: python -m intake.manage list")
    return user


def cmd_passwd(args):
    user = _require(args.username)
    if not user:
        return 1
    password = _ask_password(args.username)
    # איפוס סיסמה גם משחרר נעילה — אחרת אי אפשר להיכנס עם הסיסמה החדשה
    store.update_user(user["id"], password=password, failed_count=0,
                      locked_until="", active=True)
    print(f"✓ הסיסמה של '{args.username}' עודכנה, והחשבון פעיל ומשוחרר.")
    return 0


def cmd_unlock(args):
    user = _require(args.username)
    if not user:
        return 1
    store.update_user(user["id"], failed_count=0, locked_until="", active=True)
    print(f"✓ '{args.username}' משוחרר ופעיל.")
    return 0


def cmd_phone(args):
    user = _require(args.username)
    if not user:
        return 1
    store.update_user(user["id"], phone=args.phone)
    print(f"✓ הטלפון של '{args.username}' עודכן ל-{store.normalize_phone(args.phone)}.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m intake.manage",
        description="ניהול משתמשי ממשק קליטת הספקים")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list", help="רשימת המשתמשים")

    create = subparsers.add_parser("create", help="יצירת משתמש")
    create.add_argument("username")
    create.add_argument("--admin", action="store_true", help="הרשאת מנהל")
    create.add_argument("--phone", default="", help="טלפון לקודי אימות")
    create.add_argument("--name", default="", help="שם לתצוגה")

    for name, help_text in (("passwd", "איפוס סיסמה"), ("unlock", "שחרור חשבון")):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("username")

    phone = subparsers.add_parser("phone", help="עדכון טלפון")
    phone.add_argument("username")
    phone.add_argument("phone")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1

    store.init()
    return {
        "list": cmd_list, "create": cmd_create, "passwd": cmd_passwd,
        "unlock": cmd_unlock, "phone": cmd_phone,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
