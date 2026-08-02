#!/usr/bin/env bash
# ---------------------------------------------------------------------
# מרים את כל ה-Stack המקומי: PostgreSQL → מנוע פענוח → API → Frontend.
# שימוש:  ./scripts/dev-up.sh   (Ctrl+C לעצירה)
# ---------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD

PGPORT="${PGPORT:-5432}"
export PGHOST="${PGHOST:-127.0.0.1}"
export PGUSER="${PGUSER:-postgres}"

say() { printf '\n\033[1;36m── %s\033[0m\n' "$1"; }

say "1/4 מסד נתונים"
createdb -p "$PGPORT" pensionos 2>/dev/null || echo "   (המסד כבר קיים)"
for f in db/migrations/*.sql; do
  psql -p "$PGPORT" -d pensionos -v ON_ERROR_STOP=1 -q -f "$f"
done
psql -p "$PGPORT" -d pensionos -v ON_ERROR_STOP=1 -q -f db/dev/local-setup.sql
psql -p "$PGPORT" -d pensionos -v ON_ERROR_STOP=1 -f db/tests/rls_test.sql 2>&1 \
  | grep -E 'PASS|FAIL' || true

say "2/4 מנוע פענוח (:8081)"
cd "$ROOT/services/parser"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -e ".[dev,server]"
[ -f tests/fixtures/01_clean_menora.xml ] || .venv/bin/python tools/make_fixtures.py
.venv/bin/uvicorn pensionos_parser.server:app --port 8081 --host 127.0.0.1 \
  > /tmp/pensionos-parser.log 2>&1 &
PARSER_PID=$!

say "3/4 API (:8080)"
cd "$ROOT/apps/api"
[ -d node_modules ] || npm ci
[ -f .env ] || cp .env.example .env
npx tsc -p tsconfig.json
set -a; . ./.env; set +a
node dist/main.js > /tmp/pensionos-api.log 2>&1 &
API_PID=$!

say "4/4 Frontend (:3000)"
cd "$ROOT/apps/web"
[ -d node_modules ] || npm ci
[ -f .env.local ] || printf 'API_URL=http://127.0.0.1:8080\nDEV_TENANT_ID=11111111-1111-1111-1111-111111111111\nDEV_USER_ID=aaaaaaaa-0000-0000-0000-000000000001\nDEV_ROLE=agency_admin\n' > .env.local
npx next build > /tmp/pensionos-web-build.log 2>&1
npx next start -p 3000 > /tmp/pensionos-web.log 2>&1 &
WEB_PID=$!

trap 'kill $PARSER_PID $API_PID $WEB_PID 2>/dev/null' EXIT INT TERM
sleep 5

printf '\n\033[1;32m✔ הכל למעלה\033[0m\n'
echo "   Frontend  http://localhost:3000"
echo "   API       http://localhost:8080"
echo "   Parser    http://localhost:8081/internal/docs"
echo "   לוגים     /tmp/pensionos-*.log"
echo
echo "   הרצת ההדגמה:  ./scripts/demo.sh"
wait
