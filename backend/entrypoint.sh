#!/bin/sh
set -e

python manage.py migrate --noinput
# Creates any missing demo data (never overwrites existing rows) and embeds new or changed
# products; safe to run on every start.
python manage.py bootstrap

# gthread workers: each streaming (SSE) chat response holds a thread, not a whole worker.
exec gunicorn -c gunicorn.conf.py config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --worker-class gthread --workers "${GUNICORN_WORKERS:-2}" --threads "${GUNICORN_THREADS:-8}" \
    --timeout 120 --access-logfile -
