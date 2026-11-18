#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py createcachetable  # the shared cache for AI results (no-op if it exists)
# Creates any missing demo data (never overwrites existing rows) and embeds new or changed
# products; safe to run on every start.
python manage.py bootstrap
# Work out review summaries, listing checks and fit advice in the background, so product pages open
# instantly when a slower model (the local one) is in use. Failures fall back to the offline rules.
# The subshell always exits 0: gunicorn (PID 1 after exec) reaps it, and must never see an error code.
(python manage.py warm_ai --quiet || true) &

# gthread workers: each streaming (SSE) chat response holds a thread, not a whole worker.
exec gunicorn -c gunicorn.conf.py config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --worker-class gthread --workers "${GUNICORN_WORKERS:-2}" --threads "${GUNICORN_THREADS:-8}" \
    --timeout 120 --access-logfile -
