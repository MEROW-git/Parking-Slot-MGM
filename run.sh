#!/usr/bin/env bash
set -euo pipefail

APP_PORT="${PORT:-3000}"
MODE="${1:-serve}"

if [ -x ".venv/bin/python" ] && .venv/bin/python -c "import sys" >/dev/null 2>&1; then
    PYTHON_CMD=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1 && python3 -c "import sys" >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1 && python -c "import sys" >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    echo "SomPark requires Python 3, but no Python executable was found." >&2
    exit 1
fi

# AI Studio imports run in a Node-oriented workspace, so install the Python
# dependencies when its environment has not installed them yet. Production
# container images should install requirements.txt during their build step.
if ! "$PYTHON_CMD" -c "import django, gunicorn" >/dev/null 2>&1; then
    "$PYTHON_CMD" -m pip install -r requirements.txt
fi

"$PYTHON_CMD" manage.py collectstatic --noinput

if [ "$MODE" = "--build" ]; then
    "$PYTHON_CMD" manage.py check
    exit 0
fi

"$PYTHON_CMD" manage.py migrate --noinput

echo "Starting SomPark Django on 0.0.0.0:${APP_PORT}..."
exec "$PYTHON_CMD" -m gunicorn \
    --bind "0.0.0.0:${APP_PORT}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-60}" \
    parking_management.wsgi:application
