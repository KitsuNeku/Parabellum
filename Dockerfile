# Flask + gunicorn image used by Fly.io.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for psycopg2 and reportlab fonts.
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Fly injects PORT; default to 8080 for local docker runs.
ENV PORT=8080
EXPOSE 8080

CMD gunicorn app:app --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT
