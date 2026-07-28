# -*- coding: utf-8 -*-
"""
נקודת כניסה ל-Vercel (Python serverless / WSGI).
Vercel מזהה את המשתנה `app` (אפליקציית Flask) ומגיש דרכו את כל הבקשות.
הקוד עצמו יושב ב-file-loader/ — לכן מוסיפים אותו ל-sys.path.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "file-loader"))

from webapp import app  # noqa: E402  (חייב לבוא אחרי עדכון ה-sys.path)

# Vercel משתמש ב-`app` כ-WSGI application.
