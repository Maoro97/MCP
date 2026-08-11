# -*- coding: utf-8 -*-
"""
views.py — הנתיבים של ממשק קליטת הספקים (Blueprint בשם `intake`)

מבנה הממשק:
    /intake/login      מסך התחברות
    /intake/           מסך הבית — מצב החיבור וקליטות אחרונות
    /intake/new        אשף קליטת ספק חדש (כולל אימות בסמס)
    /intake/history    יומן הקליטות
    /intake/settings   חיבור לפריוריטי + הגדרות אימות  (מנהל בלבד)
    /intake/users      ניהול משתמשים                    (מנהל בלבד)

כל פעולה שמשנה משהו עוברת ב-POST עם אסימון CSRF, וכל נתיבי ה-API מחזירים JSON.
"""

import datetime as _dt
import logging
import secrets

from flask import (
    Blueprint, jsonify, redirect, render_template, request, session, url_for,
)

from . import auth, otp as otp_module, priority, schema, security, store

log = logging.getLogger("intake")

bp = Blueprint("intake", __name__, url_prefix="/intake")

SCREEN = "SUPPLIERS"        # המסך היחיד שמוגדר כרגע; להוספת מסך — ראו schema.py
_CSRF_KEY = "intake_csrf"


# ---------------------------------------------------------------------------
# עזרי בקשה
# ---------------------------------------------------------------------------
def csrf_token():
    token = session.get(_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_CSRF_KEY] = token
    return token


def _csrf_ok():
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    expected = session.get(_CSRF_KEY) or ""
    return bool(expected) and secrets.compare_digest(sent, expected)


@bp.before_request
def _guard():
    """
    שער כניסה אחיד: הקמה ראשונית, בדיקת CSRF, וחסימת ענן ללא הגדרות.
    בדיקת ההתחברות עצמה נעשית בעוטפים (`login_required`) בכל נתיב.
    """
    store.init()

    if request.method in ("POST", "PUT", "DELETE", "PATCH") and not _csrf_ok():
        if request.path.startswith("/intake/api/"):
            return jsonify(error="פג תוקף העמוד. רעננו והתחילו מחדש."), 400
        return render_template("intake/message.html", csrf=csrf_token(),
                               kind="error", title="בקשה לא תקינה",
                               body="פג תוקף העמוד. חזרו למסך הקודם ורעננו."), 400

    if auth.needs_setup():
        auth.bootstrap_admin()

    if auth.needs_setup() and request.endpoint != "intake.setup":
        if auth.setup_allowed():
            return redirect(url_for("intake.setup"))
        return render_template("intake/message.html", csrf=csrf_token(),
                               kind="error", title="הממשק עוד לא הוקם",
                               body="כדי לפתוח את הממשק, הגדירו במשתני הסביבה "
                                    "INTAKE_ADMIN_USER ו-INTAKE_ADMIN_PASSWORD "
                                    "ובצעו הפעלה מחדש."), 503
    return None


@bp.context_processor
def _template_context():
    user = auth.current_user()
    return {
        "csrf": csrf_token(),
        "user": user,
        "is_admin": bool(user and user["role"] == "admin"),
    }


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _config():
    return store.get_config()


def client_from_config(config):
    """בונה לקוח פריוריטי מההגדרות השמורות."""
    return priority.PriorityClient(
        url=config.get("priority_url"),
        auth_method=config.get("priority_auth") or "token",
        token=config.get("priority_token_secret") or "",
        username=config.get("priority_username") or "",
        password=config.get("priority_password_secret") or "",
        verify_tls=(config.get("priority_verify_tls") or "1") == "1",
    )


def _advanced(config):
    return (config.get("advanced_fields") or "0") == "1"


# ---------------------------------------------------------------------------
# הקמה והתחברות
# ---------------------------------------------------------------------------
@bp.route("/setup", methods=["GET", "POST"])
def setup():
    if not auth.needs_setup():
        return redirect(url_for("intake.login"))
    if not auth.setup_allowed():
        return render_template("intake/message.html", kind="error",
                               title="הקמה חסומה",
                               body="בפריסה בענן יש להקים את משתמש המנהל דרך "
                                    "משתני הסביבה INTAKE_ADMIN_USER ו-INTAKE_ADMIN_PASSWORD."), 403

    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        error = security.password_problem(password)
        if not username:
            error = "יש להזין שם משתמש"
        if not error:
            store.create_user(username=username, password=password,
                              display_name=(request.form.get("display_name") or "").strip(),
                              phone=(request.form.get("phone") or "").strip(),
                              role="admin")
            user = store.get_user(username)
            auth.start_session(user)
            return redirect(url_for("intake.settings"))
    return render_template("intake/setup.html", error=error)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if auth.current_user():
        return redirect(url_for("intake.home"))
    error = None
    if request.method == "POST":
        user, error = auth.attempt_login(request.form.get("username"),
                                         request.form.get("password"))
        if user:
            auth.start_session(user)
            nxt = request.form.get("next") or ""
            return redirect(nxt if nxt.startswith("/intake") else url_for("intake.home"))
    return render_template("intake/login.html", error=error,
                           next=request.args.get("next", ""))


@bp.route("/logout")
def logout():
    auth.end_session()
    return redirect(url_for("intake.login"))


# ---------------------------------------------------------------------------
# מסך הבית
# ---------------------------------------------------------------------------
@bp.route("/")
@auth.login_required
def home(user):
    config = _config()
    return render_template(
        "intake/home.html",
        ready=store.config_is_ready(config),
        config=config,
        stats=store.submission_stats(),
        recent=store.list_submissions(limit=5),
        otp_channel_label=otp_module.CHANNEL_LABELS.get(config.get("otp_channel"), ""),
    )


# ---------------------------------------------------------------------------
# אשף הקליטה
# ---------------------------------------------------------------------------
@bp.route("/new")
@auth.login_required
def new_supplier(user):
    config = _config()
    if not store.config_is_ready(config):
        return redirect(url_for("intake.settings") if user["role"] == "admin"
                        else url_for("intake.home"))

    form = schema.build_form(SCREEN, include_advanced=_advanced(config))
    phone_mode = config.get("otp_phone_mode") or "user"
    return render_template(
        "intake/wizard.html",
        form=form,
        today=_dt.date.today().isoformat(),
        phone_mode=phone_mode,
        user_phone_masked=security.mask_phone(user.get("phone")),
        has_user_phone=bool(user.get("phone")),
        otp_channel=config.get("otp_channel"),
        otp_ttl=config.get("otp_ttl_minutes"),
    )


@bp.route("/api/validate", methods=["POST"])
@auth.login_required
def api_validate(user):
    config = _config()
    values, errors, warnings = schema.validate_payload(
        SCREEN, _json_body().get("values") or {}, include_advanced=_advanced(config))
    return jsonify(values=values, errors=errors, warnings=warnings,
                   ok=not errors)


@bp.route("/api/otp/send", methods=["POST"])
@auth.login_required
def api_otp_send(user):
    config = _config()
    body = _json_body()
    values, errors, _warnings = schema.validate_payload(
        SCREEN, body.get("values") or {}, include_advanced=_advanced(config))
    if errors:
        return jsonify(error="יש להשלים את השדות החסרים לפני שליחת הקוד.",
                       errors=errors), 400
    try:
        result = otp_module.send_code(user, body.get("phone"), SCREEN, values, config)
    except otp_module.OtpError as exc:
        return jsonify(error=str(exc)), 400
    log.info("OTP sent by user=%s to %s via %s", user["username"],
             result["phone_masked"], result["channel"])
    return jsonify(**result)


@bp.route("/api/otp/verify", methods=["POST"])
@auth.login_required
def api_otp_verify(user):
    config = _config()
    body = _json_body()
    values, errors, _warnings = schema.validate_payload(
        SCREEN, body.get("values") or {}, include_advanced=_advanced(config))
    if errors:
        return jsonify(error="פרטי הספק אינם תקינים.", errors=errors), 400
    try:
        otp_module.verify_code(user, body.get("otp_id"), body.get("code"), SCREEN, values)
    except otp_module.OtpError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True, message="הטלפון אומת. אפשר לטעון את הספק.")


@bp.route("/api/submit", methods=["POST"])
@auth.login_required
def api_submit(user):
    config = _config()
    if not store.config_is_ready(config):
        return jsonify(error="לא הוגדר חיבור לפריוריטי."), 400

    body = _json_body()
    include_advanced = _advanced(config)
    values, errors, warnings = schema.validate_payload(
        SCREEN, body.get("values") or {}, include_advanced=include_advanced)
    if errors:
        return jsonify(error="יש שדות שאינם תקינים.", errors=errors), 400

    # ---- שער האבטחה: בלי אישור OTP תקף לרשומה הזו — לא נכנסים לפריוריטי ----
    try:
        otp_record = otp_module.check_verified(user, body.get("otp_id"), SCREEN, values)
    except otp_module.OtpError as exc:
        return jsonify(error=str(exc), need_otp=True), 400

    form = schema.build_form(SCREEN, include_advanced=include_advanced)
    entity, key_field = form["entity"], form["key_field"]
    key_value = values.get(key_field, "")
    client = client_from_config(config)

    # בדיקת כפילות לפני הכתיבה — עדיף להיעצר כאן מאשר לקבל שגיאה מפריוריטי
    if key_value and (config.get("duplicate_check") or "1") == "1":
        try:
            if client.find(entity, key_field, key_value, select=[key_field]):
                return jsonify(error=f"ספק עם מספר '{key_value}' כבר קיים בפריוריטי."), 409
        except priority.PriorityError as exc:
            log.warning("duplicate check failed: %s", exc.message)

    payload = schema.to_odata(SCREEN, values, include_advanced=include_advanced)
    entry = {
        "user_id": user["id"], "username": user["username"], "screen": SCREEN,
        "key_value": key_value, "supplier_name": values.get("SUPDES", ""),
        "phone": security.mask_phone(otp_record["phone"]), "payload": payload,
        "otp_id": otp_record["id"],
    }

    # תופסים את הקוד *לפני* הכתיבה — אישור אחד, ספק אחד, גם אם נשלחו שתי
    # בקשות במקביל. אם הכתיבה נכשלה הקוד משוחרר, כי לא נוצר שום דבר.
    if not store.claim_otp(otp_record["id"]):
        return jsonify(error="האישור כבר בשימוש. שלחו קוד חדש.", need_otp=True), 409

    try:
        created = client.create(entity, payload)
    except priority.PriorityError as exc:
        store.release_otp(otp_record["id"])
        entry.update(status="failed", message=exc.message, response={"detail": exc.detail})
        store.add_submission(entry)
        log.warning("intake create failed user=%s: %s", user["username"], exc.message)
        return jsonify(error=exc.message, detail=exc.detail), 502

    created_key = created.get(key_field) or key_value
    entry.update(status="created", key_value=created_key,
                 message="נקלט בהצלחה", response=created)
    submission_id = store.add_submission(entry)
    store.purge_old_otp()

    log.info("supplier created user=%s key=%s", user["username"], created_key)
    return jsonify(ok=True, submission_id=submission_id, key=created_key,
                   name=values.get("SUPDES", ""), warnings=warnings,
                   message=f"הספק '{values.get('SUPDES', '')}' נקלט בפריוריטי.")


# ---------------------------------------------------------------------------
# יומן קליטות
# ---------------------------------------------------------------------------
@bp.route("/history")
@auth.login_required
def history(user):
    only_mine = user["role"] != "admin"
    rows = store.list_submissions(limit=200, user_id=user["id"] if only_mine else None)
    return render_template("intake/history.html", rows=rows, only_mine=only_mine)


@bp.route("/api/history/<int:submission_id>")
@auth.login_required
def api_history_item(user, submission_id):
    row = store.get_submission(submission_id)
    if not row or (user["role"] != "admin" and row["user_id"] != user["id"]):
        return jsonify(error="הרשומה לא נמצאה."), 404
    return jsonify(row=row)


# ---------------------------------------------------------------------------
# הגדרות (מנהל)
# ---------------------------------------------------------------------------
_CHECKBOXES = ("priority_verify_tls", "advanced_fields", "duplicate_check")


@bp.route("/settings", methods=["GET", "POST"])
@auth.admin_required
def settings(user):
    message = error = None
    if request.method == "POST":
        changes = {}
        for key in store.DEFAULTS:
            if key in _CHECKBOXES:
                changes[key] = "1" if request.form.get(key) else "0"
            elif key in request.form:
                value = request.form.get(key) or ""
                # שדה סוד שנשלח ריק = "אל תשנה" (הטופס לא מציג את הערך הקיים)
                if key.endswith("_secret") and value == "":
                    continue
                changes[key] = value.strip() if not key.endswith("_secret") else value
        if changes.get("priority_url") and not priority.looks_like_service_url(
                changes["priority_url"]):
            error = ("כתובת השירות צריכה להיראות כך: "
                     "https://<שרת>/odata/Priority/tabula.ini/<חברה>")
        else:
            store.set_config(changes, updated_by=user["username"])
            message = "ההגדרות נשמרו."

    config = _config()
    return render_template(
        "intake/settings.html", config=config, message=message, error=error,
        channels=otp_module.CHANNEL_LABELS,
        secrets_encrypted=security.secrets_encrypted(),
        has_token=bool(config.get("priority_token_secret")),
        has_password=bool(config.get("priority_password_secret")),
        has_otp_secret=bool(config.get("otp_secret")),
    )


@bp.route("/api/check-fields", methods=["POST"])
@auth.admin_required
def api_check_fields(user):
    """
    משווה את שדות הטופס מול $metadata של פריוריטי.

    ייצוא עמודות המסך כולל עמודות שאינן חשופות ב-OData (למשל FOREIGN), ולכן
    בלי הבדיקה הזו מגלים אותן רק כשפריוריטי דוחה טעינה — שדה אחד בכל פעם.
    """
    config = _config()
    if not store.config_is_ready(config):
        return jsonify(error="לא הוגדר חיבור לפריוריטי."), 400

    form = schema.build_form(SCREEN, include_advanced=True)
    try:
        available = client_from_config(config).entity_properties(form["entity"])
    except priority.PriorityError as exc:
        return jsonify(error=exc.message, detail=exc.detail), 400

    shown, hidden = [], []
    for step in form["steps"]:
        for field in step["fields"]:
            if field["name"] in available:
                continue
            (hidden if step["id"] == "advanced" else shown).append(
                {"name": field["name"], "label": field["label"], "step": step["title"]})

    total = sum(len(step["fields"]) for step in form["steps"])
    return jsonify(ok=not shown and not hidden, checked=total,
                   available=len(available), missing=shown + hidden,
                   entity=form["entity"])


@bp.route("/api/test-connection", methods=["POST"])
@auth.admin_required
def api_test_connection(user):
    config = _config()
    body = _json_body()
    # אפשר לבדוק ערכים שהוקלדו בטופס לפני שמירה
    for key in ("priority_url", "priority_auth", "priority_username"):
        if body.get(key):
            config[key] = body[key]
    if body.get("priority_token_secret"):
        config["priority_token_secret"] = body["priority_token_secret"]
    if body.get("priority_password_secret"):
        config["priority_password_secret"] = body["priority_password_secret"]
    if "priority_verify_tls" in body:
        config["priority_verify_tls"] = "1" if body["priority_verify_tls"] else "0"

    if not config.get("priority_url"):
        return jsonify(error="לא הוגדרה כתובת שירות."), 400
    try:
        result = client_from_config(config).test_connection(
            schema.build_form(SCREEN)["entity"])
    except priority.PriorityError as exc:
        return jsonify(error=exc.message, detail=exc.detail), 400
    return jsonify(**result)


# ---------------------------------------------------------------------------
# משתמשים (מנהל)
# ---------------------------------------------------------------------------
@bp.route("/users", methods=["GET", "POST"])
@auth.admin_required
def users(user):
    message = error = None
    if request.method == "POST":
        action = request.form.get("action")
        try:
            message, error = _user_action(user, action)
        except ValueError as exc:
            error = str(exc)
    return render_template("intake/users.html", rows=store.list_users(),
                           message=message, error=error)


def _user_action(actor, action):
    """מבצע פעולת ניהול משתמשים. מחזיר (message, error)."""
    form = request.form
    if action == "create":
        username = (form.get("username") or "").strip()
        password = form.get("password") or ""
        problem = security.password_problem(password)
        if not username:
            return None, "יש להזין שם משתמש"
        if problem:
            return None, problem
        created = store.create_user(
            username=username, password=password,
            display_name=(form.get("display_name") or "").strip(),
            phone=(form.get("phone") or "").strip(),
            role="admin" if form.get("role") == "admin" else "user")
        if not created:
            return None, f"שם המשתמש '{username}' כבר קיים"
        return f"המשתמש '{username}' נוצר.", None

    target_id = int(form.get("user_id") or 0)
    target = store.get_user_by_id(target_id)
    if not target:
        return None, "המשתמש לא נמצא"

    if action == "update":
        changes = {
            "display_name": (form.get("display_name") or "").strip(),
            "phone": (form.get("phone") or "").strip(),
            "role": "admin" if form.get("role") == "admin" else "user",
        }
        if target_id == actor["id"] and changes["role"] != "admin":
            return None, "אי אפשר להוריד לעצמכם הרשאת ניהול"
        store.update_user(target_id, **changes)
        return f"הפרטים של '{target['username']}' עודכנו.", None

    if action == "password":
        password = form.get("password") or ""
        problem = security.password_problem(password)
        if problem:
            return None, problem
        store.update_user(target_id, password=password, failed_count=0, locked_until="")
        return f"הסיסמה של '{target['username']}' עודכנה.", None

    if action == "toggle":
        if target_id == actor["id"]:
            return None, "אי אפשר לחסום את עצמכם"
        store.update_user(target_id, active=not target["active"])
        state = "שוחרר" if not target["active"] else "נחסם"
        return f"המשתמש '{target['username']}' {state}.", None

    if action == "delete":
        if target_id == actor["id"]:
            return None, "אי אפשר למחוק את עצמכם"
        store.delete_user(target_id)
        return f"המשתמש '{target['username']}' נמחק.", None

    return None, "פעולה לא מוכרת"


# ---------------------------------------------------------------------------
# החשבון שלי
# ---------------------------------------------------------------------------
@bp.route("/account", methods=["GET", "POST"])
@auth.login_required
def account(user):
    message = error = None
    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        if not security.verify_password(current, user["password"]):
            error = "הסיסמה הנוכחית שגויה"
        else:
            error = security.password_problem(new)
            if not error:
                store.update_user(user["id"], password=new)
                message = "הסיסמה עודכנה."
    return render_template("intake/account.html", message=message, error=error,
                           phone_masked=security.mask_phone(user.get("phone")))
