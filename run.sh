#!/bin/bash
set -e

# Prefer project virtualenv if present
if [ -x ".venv/bin/gunicorn" ]; then
    exec .venv/bin/gunicorn --bind 0.0.0.0:3000 --workers 2 --timeout 60 parking_management.wsgi:application
fi

if command -v gunicorn >/dev/null 2>&1; then
    exec gunicorn --bind 0.0.0.0:3000 --workers 2 --timeout 60 parking_management.wsgi:application
fi

exec python3 -m gunicorn --bind 0.0.0.0:3000 --workers 2 --timeout 60 parking_management.wsgi:application
