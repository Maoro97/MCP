# ============================================================================
# Dockerfile אוניברסלי — לפריסת הכלי בכל ספק שתומך ב-Docker
# (Fly.io / Google Cloud Run / Railway / Azure ועוד).
# בנייה מקומית:   docker build -t priority-file-loader .
# הרצה מקומית:    docker run -p 8000:8000 priority-file-loader
# ============================================================================
FROM python:3.11-slim

WORKDIR /app

# התקנת התלויות תחילה (שכבת מטמון יעילה)
COPY file-loader/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# קוד הכלי
COPY file-loader/ ./

ENV PORT=8000
EXPOSE 8000

# worker יחיד (מצב-ריצה בזיכרון) + threads לריבוי משתמשים במקביל
CMD ["sh", "-c", "gunicorn webapp:app --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:${PORT}"]
