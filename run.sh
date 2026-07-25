#!/usr/bin/env bash
# Start the terminal from a fresh checkout: one venv, the API on 8000, the UI on
# 8501. Idempotent. Ctrl-C stops both. Set ER_THEME=light for the light palette.
set -euo pipefail
cd "$(dirname "$0")"

VENV="backend/.venv"
PY="$VENV/bin/python"
API_PORT="${API_PORT:-8000}"
UI_PORT="${UI_PORT:-8501}"

if [ ! -d "$VENV" ]; then
  echo "Creating virtualenv and installing dependencies…"
  python3 -m venv "$VENV"
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r backend/requirements.txt
fi

# Create the schema (and apply migrations) if the database is absent, then seed the
# universe when it is empty. Both steps are no-ops once done.
"$PY" -c "import sys; sys.path.insert(0,'backend'); import db; db.init()"
if [ -z "$("$PY" -c "import sys; sys.path.insert(0,'backend'); import db; c=db.get_connection(); print(c.execute('SELECT COUNT(*) FROM companies').fetchone()[0])")" ] \
   || [ "$("$PY" -c "import sys; sys.path.insert(0,'backend'); import db; c=db.get_connection(); print(c.execute('SELECT COUNT(*) FROM companies').fetchone()[0])")" = "0" ]; then
  echo "Seeding the 18-company universe…"
  ( cd backend && "../$PY" seed.py ) || echo "Seed step reported an issue; check network for CIK resolution."
fi

echo "API  → http://localhost:$API_PORT"
echo "UI   → http://localhost:$UI_PORT"

"$VENV/bin/uvicorn" main:app --app-dir backend --port "$API_PORT" --reload &
API_PID=$!
ER_API_BASE="http://localhost:$API_PORT" \
  "$VENV/bin/streamlit" run frontend/streamlit_app.py --server.port "$UI_PORT" &
UI_PID=$!

trap 'echo; echo "Stopping…"; kill $API_PID $UI_PID 2>/dev/null || true' INT TERM
wait
