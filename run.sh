#!/bin/bash
set -e

# Port configuration for container reverse proxy (port 3000)
PORT="3000"

# Load .env if present
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Ensure default development secrets if not set in deployment environment
if [ -z "$SECRET_KEY" ]; then
    export SECRET_KEY="sompark-local-dev-secret-key-for-preview"
fi

if [ -z "$SESSION_SECRET" ]; then
    export SESSION_SECRET="sompark-session-secret-preview-12345"
fi

# Detect whether Python and Django are available in the container
HAS_DJANGO=false
PYTHON_CMD=""

if [ -x ".venv/bin/python" ] && .venv/bin/python -c "import django" >/dev/null 2>&1; then
    HAS_DJANGO=true
    PYTHON_CMD=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1 && python3 -c "import django" >/dev/null 2>&1; then
    HAS_DJANGO=true
    PYTHON_CMD="python3"
fi

if [ "$HAS_DJANGO" = true ]; then
    echo "Starting SomPark Django backend on port $PORT..."
    $PYTHON_CMD manage.py migrate --noinput || true

    if [ -x ".venv/bin/gunicorn" ]; then
        exec .venv/bin/gunicorn --bind "0.0.0.0:${PORT}" --workers 2 --timeout 60 parking_management.wsgi:application
    elif command -v gunicorn >/dev/null 2>&1; then
        exec gunicorn --bind "0.0.0.0:${PORT}" --workers 2 --timeout 60 parking_management.wsgi:application
    else
        exec $PYTHON_CMD manage.py runserver "0.0.0.0:${PORT}"
    fi
fi

# When running in a Node.js container (e.g. Cloud Run preview environment), run server.ts
echo "Launching SomPark Node service on port $PORT..."
exec node server.ts
