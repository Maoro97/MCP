@echo off
REM ===========================================================================
REM  הפעלת ממשק קליטת הספקים בווינדוס — לחיצה כפולה, או "run-intake" בטרמינל.
REM
REM  מה הוא עושה:
REM    1. עובר לתיקייה שבה הקובץ הזה יושב
REM    2. מייצר בפעם הראשונה שני מפתחות אקראיים ושומר אותם ב-.intake-env.bat
REM       (הקובץ מוחרג מ-git — המפתחות שלכם, לא של אף אחד אחר)
REM    3. מתקין תלויות אם צריך
REM    4. מרים את השרת ופותח את הדפדפן
REM
REM  לעצירה: Ctrl+C בחלון הזה.
REM ===========================================================================
cd /d "%~dp0"

REM --- איתור פייתון: קודם python, ואם אין אז py ---
set PY=python
%PY% --version >nul 2>&1 || set PY=py
%PY% --version >nul 2>&1 || (
  echo.
  echo [שגיאה] לא נמצא Python. התקינו Python 3.11+ מ-python.org
  echo         וסמנו בהתקנה "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

REM --- מפתחות: נוצרים פעם אחת ונשמרים מקומית ---
if not exist ".intake-env.bat" (
  echo יוצר מפתחות אבטחה מקומיים...
  %PY% -c "import secrets; f=open('.intake-env.bat','w'); f.write('set SECRET_KEY='+secrets.token_hex(32)+'\n'); f.write('set INTAKE_SECRET='+secrets.token_hex(32)+'\n'); f.close()"
)
call .intake-env.bat

REM --- תלויות ---
%PY% -c "import flask, pandas, yaml, openpyxl" >nul 2>&1 || (
  echo מתקין תלויות, זה ייקח דקה...
  %PY% -m pip install -r requirements.txt
)

echo.
echo ============================================================
echo   ממשק קליטת ספקים פועל
echo   http://127.0.0.1:5000/intake/
echo   לעצירה: Ctrl+C
echo ============================================================
echo.

start "" http://127.0.0.1:5000/intake/
%PY% webapp.py
