/* ==========================================================================
   אשף קליטת ספק — ניווט בין שלבים, ולידציה חיה, אימות בסמס וטעינה.

   העיקרון: הדפדפן עוזר, השרת מחליט. כל בדיקה שרצה כאן רצה שוב בשרת לפני
   שהרשומה נשלחת לפריוריטי — כולל אישור ה-OTP, שקשור לנתונים הספציפיים.
   ========================================================================== */
(function () {
  "use strict";

  var W = window.WIZARD;
  var form = document.getElementById("wizard");
  var rail = document.getElementById("rail");
  var nav = document.getElementById("nav");
  var stepCount = document.getElementById("stepcount");
  var cards = Array.prototype.slice.call(form.querySelectorAll(".stepcard"));
  var lastStep = cards.length - 1;             // שלב הסיכום
  var current = 0;
  var otpId = null;
  var otpVerified = false;

  var labelOf = {};
  W.names.forEach(function (name, i) { labelOf[name] = W.labels[i]; });

  /* ---------- קריאת ערכי הטופס ---------- */
  function values() {
    var out = {};
    form.querySelectorAll("[data-field]").forEach(function (el) {
      out[el.dataset.field] = el.value;
    });
    return out;
  }

  function fieldBox(name) { return document.getElementById("w_" + name); }

  function clearMarks() {
    form.querySelectorAll(".field").forEach(function (box) {
      box.classList.remove("bad", "warn");
      var err = box.querySelector(".msg.err");
      var warn = box.querySelector(".msg.warn");
      if (err) err.textContent = "";
      if (warn) warn.textContent = "";
    });
  }

  function mark(errors, warnings) {
    clearMarks();
    Object.keys(errors || {}).forEach(function (name) {
      var box = fieldBox(name);
      if (!box) return;
      box.classList.add("bad");
      box.querySelector(".msg.err").textContent = errors[name];
    });
    Object.keys(warnings || {}).forEach(function (name) {
      var box = fieldBox(name);
      if (!box || box.classList.contains("bad")) return;
      box.classList.add("warn");
      box.querySelector(".msg.warn").textContent = warnings[name];
    });
  }

  /* ---------- ולידציה מול השרת ---------- */
  var validating = null;
  function validate() {
    validating = api(W.urls.validate, { values: values() }).then(function (data) {
      mark(data.errors, data.warnings);
      return data;
    });
    return validating;
  }

  /* שלב נחשב תקין אם אף שדה שלו אינו מסומן כשגוי */
  function stepErrors(index, errors) {
    var names = W.groups[index] || [];
    return names.filter(function (name) { return errors && errors[name]; });
  }

  /* ---------- ניווט ---------- */
  function show(index) {
    current = Math.max(0, Math.min(lastStep, index));
    cards.forEach(function (card, i) { card.hidden = i !== current; });
    nav.hidden = current === lastStep;
    stepCount.textContent = "שלב " + (current + 1) + " מתוך " + (lastStep + 1);
    /* בשלב הראשון אין לאן לחזור */
    form.querySelectorAll("[data-back]").forEach(function (b) { b.hidden = current === 0; });
    paintRail();
    window.scrollTo({ top: 0, behavior: "smooth" });
    var first = cards[current].querySelector("input:not([type=hidden]), select");
    if (first && current !== lastStep) first.focus({ preventScroll: true });
    if (current === lastStep) buildSummary();
  }

  function paintRail() {
    Array.prototype.slice.call(rail.children).forEach(function (btn, i) {
      btn.classList.toggle("now", i === current);
      btn.classList.toggle("done", i < current);
    });
  }

  async function goNext() {
    var data = await validate().catch(function () { return null; });
    if (!data) { toast("לא ניתן לבדוק את הנתונים כרגע", "err"); return; }
    var bad = stepErrors(current, data.errors);
    if (bad.length) {
      toast("יש להשלים: " + bad.map(function (n) { return labelOf[n] || n; }).join(", "), "err");
      var box = fieldBox(bad[0]);
      if (box) box.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    show(current + 1);
  }

  /* קפיצה בסרגל: קדימה רק דרך שלבים תקינים, אחורה תמיד */
  rail.addEventListener("click", async function (event) {
    var btn = event.target.closest("[data-goto]");
    if (!btn) return;
    var target = parseInt(btn.dataset.goto, 10);
    if (target <= current) { show(target); return; }
    var data = await validate().catch(function () { return null; });
    if (!data) return;
    for (var i = current; i < target; i++) {
      if (stepErrors(i, data.errors).length) {
        toast("יש להשלים את שלב " + (i + 1) + " (" + W.steps[i] + ")", "err");
        show(i);
        return;
      }
    }
    show(target);
  });

  form.querySelectorAll("[data-next]").forEach(function (b) { b.addEventListener("click", goNext); });
  form.querySelectorAll("[data-back]").forEach(function (b) {
    b.addEventListener("click", function () { show(current - 1); });
  });

  /* בדיקה שקטה כשעוזבים שדה — סימון מיידי בלי להפריע להקלדה */
  form.addEventListener("focusout", function (event) {
    if (!event.target.dataset || !event.target.dataset.field) return;
    validate().catch(function () {});
  });

  /* Enter מקדם שלב, אבל לא בשלב האחרון (שם צריך אישור מפורש) */
  form.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && current < lastStep) {
      event.preventDefault();
      goNext();
    }
  });

  /* ---------- סיכום ---------- */
  function buildSummary() {
    var data = values();
    var summary = document.getElementById("summary");
    summary.innerHTML = "";
    W.groups.forEach(function (names, i) {
      var filled = names.filter(function (name) { return (data[name] || "").trim() !== ""; });
      if (!filled.length) return;
      var title = document.createElement("div");
      title.className = "group";
      title.textContent = W.steps[i];
      summary.appendChild(title);
      filled.forEach(function (name) {
        var row = document.createElement("div");
        row.className = "row";
        var dt = document.createElement("dt");
        dt.textContent = labelOf[name] || name;
        var dd = document.createElement("dd");
        dd.textContent = displayValue(name, data[name]);
        row.appendChild(dt);
        row.appendChild(dd);
        summary.appendChild(row);
      });
    });
  }

  function displayValue(name, value) {
    var el = document.getElementById("f_" + name);
    if (el && el.tagName === "SELECT") {
      var option = el.options[el.selectedIndex];
      if (option) return option.textContent.trim();
    }
    /* תאריך נשמר כ-ISO אבל בסיכום מוצג כמו שמקובל בארץ */
    if (el && el.type === "date" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
      var parts = value.split("-");
      return parts[2] + "/" + parts[1] + "/" + parts[0];
    }
    return value;
  }

  /* כל שינוי בנתונים מבטל אישור OTP קודם — האישור צמוד לרשומה מסוימת */
  form.addEventListener("input", function (event) {
    if (!event.target.dataset || !event.target.dataset.field) return;
    if (otpVerified) resetOtp("הפרטים השתנו — נדרש אימות מחדש.");
  });

  /* ---------- אימות בסמס ---------- */
  var otpBox = document.getElementById("otpbox");
  var sendRow = document.getElementById("otp_send_row");
  var verifyRow = document.getElementById("otp_verify_row");
  var codeInput = document.getElementById("otp_code");
  var submitBtn = document.getElementById("btn_submit");
  var otpTitle = document.getElementById("otp_title");
  var otpHint = document.getElementById("otp_hint");

  function resetOtp(message) {
    otpId = null;
    otpVerified = false;
    otpBox.classList.remove("done");
    otpTitle.textContent = "אימות בסמס";
    verifyRow.hidden = true;
    sendRow.hidden = false;
    codeInput.value = "";
    submitBtn.disabled = true;
    if (message) { otpHint.textContent = message; toast(message, "err"); }
  }

  function busy(btn, on) {
    btn.classList.toggle("busy", on);
    btn.disabled = on;
  }

  async function sendOtp(btn) {
    var data = await validate().catch(function () { return null; });
    if (!data) { toast("לא ניתן לבדוק את הנתונים כרגע", "err"); return; }
    if (Object.keys(data.errors || {}).length) {
      var first = Object.keys(data.errors)[0];
      toast("יש להשלים שדות חסרים לפני שליחת הקוד", "err");
      show(stepOf(first));
      return;
    }
    busy(btn, true);
    try {
      var phoneEl = document.getElementById("otp_phone");
      var result = await api(W.urls.send, {
        values: values(),
        phone: phoneEl ? phoneEl.value : ""
      });
      otpId = result.otp_id;
      sendRow.hidden = true;
      verifyRow.hidden = false;
      otpHint.textContent = "הקוד נשלח אל " + result.phone_masked +
        " ותקף ל-" + result.ttl_minutes + " דקות.";
      if (result.dev_code) {
        otpHint.textContent += " (מצב פיתוח — הקוד: " + result.dev_code + ")";
      }
      codeInput.focus();
      toast("הקוד נשלח", "ok");
    } catch (error) {
      toast(error.message, "err");
    } finally {
      busy(btn, false);
    }
  }

  function stepOf(fieldName) {
    for (var i = 0; i < W.groups.length; i++) {
      if (W.groups[i].indexOf(fieldName) !== -1) return i;
    }
    return 0;
  }

  document.getElementById("btn_send_otp").addEventListener("click", function () {
    sendOtp(this);
  });
  document.getElementById("btn_resend_otp").addEventListener("click", function () {
    otpId = null;
    sendOtp(this);
  });

  document.getElementById("btn_verify_otp").addEventListener("click", async function () {
    var btn = this;
    busy(btn, true);
    try {
      await api(W.urls.verify, { otp_id: otpId, code: codeInput.value, values: values() });
      otpVerified = true;
      otpBox.classList.add("done");
      otpTitle.textContent = "הטלפון אומת ✓";
      otpHint.textContent = "האישור תקף לפרטים שלמעלה בלבד. שינוי פרט כלשהו ידרוש אימות מחדש.";
      verifyRow.hidden = true;
      submitBtn.disabled = false;
      toast("אומת — אפשר לטעון", "ok");
    } catch (error) {
      toast(error.message, "err");
      codeInput.select();
    } finally {
      busy(btn, false);
    }
  });

  codeInput.addEventListener("input", function () {
    this.value = this.value.replace(/\D/g, "").slice(0, 6);
    if (this.value.length === 6) document.getElementById("btn_verify_otp").click();
  });

  /* ---------- טעינה לפריוריטי ---------- */
  submitBtn.addEventListener("click", async function () {
    var btn = this;
    busy(btn, true);
    try {
      var result = await api(W.urls.submit, { otp_id: otpId, values: values() });
      document.querySelector(".rail").hidden = true;
      form.hidden = true;
      document.getElementById("done_name").textContent = result.name || "";
      document.getElementById("done_key").textContent = result.key || "";
      document.getElementById("done").hidden = false;
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (error) {
      var problems = document.getElementById("review_problems");
      problems.innerHTML = "";
      var note = document.createElement("div");
      note.className = "note err";
      note.innerHTML = "<span>⛔</span>";
      var text = document.createElement("span");
      text.textContent = error.message;
      note.appendChild(text);
      problems.appendChild(note);
      if (error.data && error.data.errors) mark(error.data.errors, {});
      if (error.data && error.data.need_otp) resetOtp(null);
      toast(error.message, "err");
      problems.scrollIntoView({ behavior: "smooth", block: "center" });
    } finally {
      busy(btn, false);
    }
  });

  show(0);
})();
