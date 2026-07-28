# מדריך Terminal — עדכון והרצה של הכלי (צעד אחר צעד)

מדריך זה נותן לך את **בדיוק** את שורות הקוד שצריך להריץ ב-Terminal, בסדר הנכון.
מותאם ל-**Windows** (יש הערות ל-Mac/Linux היכן ששונה).

הענף שעליו נמצא הקוד:
```
claude/priority-file-loader-tool-49nxln
```

---

## 0. פתיחת ה-Terminal

- **Windows:** לחץ על תפריט התחל → הקלד `cmd` → פתח **Command Prompt**
  (או **PowerShell**). אפשר גם בתוך VS Code: תפריט `Terminal → New Terminal`.
- **Mac:** פתח את היישום **Terminal**.

---

## 1. מעבר לתיקייה של הפרויקט (`cd`)

`cd` = "change directory" — מעבר לתיקייה. הרץ:

```bat
cd C:\Users\User\MCP
```

> אם התיקייה אצלך במקום אחר — החלף את הנתיב. טיפ: אפשר לגרור את תיקיית
> הפרויקט אל חלון ה-Terminal והנתיב יודבק לבד.

לבדיקה שאתה במקום הנכון — הצג את תוכן התיקייה:
```bat
dir            :: ב-Windows
```
```bash
ls             # ב-Mac/Linux
```
אתה אמור לראות את התיקייה `file-loader`.

---

## 2. מעבר לענף הנכון ומשיכת הקוד העדכני (`git pull`)

**בפעם הראשונה בלבד** — ודא שאתה על הענף הנכון:
```bat
git fetch origin
git checkout claude/priority-file-loader-tool-49nxln
```

**בכל פעם שתרצה לקבל את העדכונים האחרונים** — הרץ:
```bat
git pull origin claude/priority-file-loader-tool-49nxln
```
`git pull` מוריד את השינויים האחרונים מהענן (GitHub) אל המחשב שלך.

לבדיקה על איזה ענף אתה נמצא כרגע:
```bat
git branch --show-current
```
(אמור להחזיר `claude/priority-file-loader-tool-49nxln`)

---

## 3. מעבר לתיקיית הכלי והתקנת הספריות

```bat
cd file-loader
pip install -r requirements.txt
```
זה מתקין את הספריות שהכלי צריך (pandas, flask וכו'). צריך להריץ שוב רק
כשמתווספת ספרייה חדשה — אין נזק להריץ בכל פעם.

> אם `pip` לא מוכר, נסה `python -m pip install -r requirements.txt`
> (ב-Mac/Linux לרוב `pip3` / `python3`).

---

## 4. הרצת הכלי

```bat
python webapp.py
```
תראה הודעה כמו:
```
פתח בדפדפן:  http://127.0.0.1:5000
```
פתח את הכתובת `http://127.0.0.1:5000` בדפדפן — הכלי פועל.

**לעצירה:** בחלון ה-Terminal לחץ `Ctrl + C`.

> Python חדש לא נטען אוטומטית: אם משכת קוד חדש (`git pull`) בזמן שהשרת רץ —
> עצור אותו ב-`Ctrl + C` והרץ שוב `python webapp.py`. בדפדפן רענן עם `Ctrl + F5`.

---

## הכול ברצף אחד (העתק-הדבק מהיר לעדכון והרצה)

```bat
cd C:\Users\User\MCP
git pull origin claude/priority-file-loader-tool-49nxln
cd file-loader
pip install -r requirements.txt
python webapp.py
```

---

## פתרון תקלות נפוצות

| התקלה | הפתרון |
|------|--------|
| `'git' is not recognized` | Git לא מותקן. התקן מ-https://git-scm.com/download/win ופתח Terminal מחדש. |
| `'python' is not recognized` | Python לא מותקן/לא ב-PATH. התקן מ-https://python.org ובחר **Add to PATH** בהתקנה. |
| `The syntax of the command is incorrect` | לרוב נתיב עם רווחים/סלאש הפוך. ב-Windows השתמש ב-`\` ולא ב-`/`. |
| `git pull` נכשל: *Your local changes would be overwritten* | שינית קבצים מקומית. כדי לבטל שינויים מקומיים ולמשוך את גרסת הענן: `git checkout -- .` ואז `git pull` שוב. (זהירות — זה מוחק שינויים מקומיים שלא נשמרו.) |
| הדפדפן לא נטען | ודא שחלון ה-Terminal עם `python webapp.py` עדיין פתוח ורץ. |
| שינוי בקוד לא מופיע | עצור (`Ctrl+C`), הרץ שוב `python webapp.py`, ורענן בדפדפן `Ctrl+F5`. |

---

## תזכורת: מתי צריך את זה בכלל?

- אם אתה מריץ את הכלי **מקומית על המחשב שלך** — המדריך הזה בשבילך.
- אם פרסת את הכלי **בענן (Render)** — אין צורך בכלום: העדכונים נפרסים
  אוטומטית בכל דחיפת קוד, והמשתמשים פשוט נכנסים לכתובת ה-https. ראה `DEPLOY.md`.
