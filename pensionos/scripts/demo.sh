#!/usr/bin/env bash
# ---------------------------------------------------------------------
# הדגמת הזרימה המלאה מקצה לקצה, מול השירותים הרצים מקומית:
#   התחברות → יצירת לקוח → קליטת קובץ מסלקה → תיק 360°
#
# דרישות מוקדמות (ראה pensionos/README.md):
#   1. PostgreSQL עם המיגרציות + db/dev/local-setup.sql
#   2. uvicorn pensionos_parser.server:app --port 8081
#   3. node dist/main.js  (API על 8080)
# ---------------------------------------------------------------------
set -euo pipefail

API="${API:-http://localhost:8080}"
FIXTURES="${FIXTURES:-$(dirname "$0")/../services/parser/tests/fixtures}"
TENANT="11111111-1111-1111-1111-111111111111"
USER_ID="aaaaaaaa-0000-0000-0000-000000000001"
CURL=(curl -s --noproxy '*')

step() { printf '\n\033[1;36m── %s\033[0m\n' "$1"; }

step "1. התחברות (dev-login)"
TOKEN=$("${CURL[@]}" -X POST "$API/v1/auth/dev-login" \
  -H 'content-type: application/json' \
  -d "{\"userId\":\"$USER_ID\",\"tenantId\":\"$TENANT\",\"role\":\"agency_admin\"}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["accessToken"])')
AUTH=(-H "authorization: Bearer $TOKEN")
echo "   טוקן התקבל (${#TOKEN} תווים)"

step "2. יצירת לקוח"
CLIENT=$("${CURL[@]}" "${AUTH[@]}" -X POST "$API/v1/clients" \
  -H 'content-type: application/json' \
  -d '{"nationalId":"039472519","firstName":"דנה","lastName":"כהן",
       "birthDate":"1984-03-17","phoneE164":"+972501234567",
       "maritalStatus":"נשואה"}')
CLIENT_ID=$(echo "$CLIENT" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("id",""))')
if [ -z "$CLIENT_ID" ]; then
  echo "   הלקוח כבר קיים — מאתר אותו"
  CLIENT_ID=$("${CURL[@]}" "${AUTH[@]}" "$API/v1/clients?q=2519" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')
fi
echo "   clientId = $CLIENT_ID"

step "3. ולידציה: ת\"ז עם ספרת ביקורת שגויה נדחית"
"${CURL[@]}" "${AUTH[@]}" -X POST "$API/v1/clients" \
  -H 'content-type: application/json' \
  -d '{"nationalId":"039472518","firstName":"בדיקה","lastName":"שלילית"}' \
  | python3 -c 'import json,sys; print("  ", json.load(sys.stdin).get("message"))'

step "4. קליטת קבצי מסלקה"
for f in 01_clean_menora.xml 04_empty_tags_and_zeros.xml 12_provider_quirk.xml; do
  printf '   %-32s ' "$f"
  "${CURL[@]}" "${AUTH[@]}" -X POST "$API/v1/clients/$CLIENT_ID/ingest" \
    -F "file=@$FIXTURES/$f" \
  | python3 -c '
import json, sys
d = json.load(sys.stdin)
if "status" not in d:
    print("שגיאה:", d.get("message")); sys.exit()
i = d["issues"]
dup = " (כבר נקלט)" if d["duplicate"] else ""
stale = f'"'"' דילוג-ישן: {d["staleSkipped"]}'"'"' if d["staleSkipped"] else ""
print(f'"'"'{d["status"]:10s} מוצרים: {d["productsPersisted"]}{stale}{dup}  '"'"'
      f'"'"'חריגים: {i["error"]+i["blocker"]} חוסמים / {i["warning"]} אזהרות'"'"')'
done

step "5. אבטחה: קובץ שאינו של הלקוח"
printf '   %-32s ' "09_subject_mismatch.xml"
"${CURL[@]}" "${AUTH[@]}" -X POST "$API/v1/clients/$CLIENT_ID/ingest" \
  -F "file=@$FIXTURES/09_subject_mismatch.xml" \
| python3 -c '
import json, sys
d = json.load(sys.stdin)
print(f'"'"'{d["status"]:10s} מוצרים שנקלטו: {d["productsPersisted"]}'"'"')
for m in d["blockingIssues"]: print("      🛑", m)'

step "6. לקוח שני — דיווח דל (מדגים את מצב \"לא התקבל\")"
CLIENT2=$("${CURL[@]}" "${AUTH[@]}" -X POST "$API/v1/clients" \
  -H 'content-type: application/json' \
  -d '{"nationalId":"021234562","firstName":"אורי","lastName":"לוי",
       "birthDate":"1971-11-02","phoneE164":"+972521112233"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))')
if [ -n "$CLIENT2" ]; then
  "${CURL[@]}" "${AUTH[@]}" -X POST "$API/v1/clients/$CLIENT2/ingest" \
    -F "file=@$FIXTURES/16_other_client_sparse.xml" > /dev/null
  echo "   clientId = $CLIENT2"
fi

step "7. תיק 360°"
"${CURL[@]}" "${AUTH[@]}" "$API/v1/clients/$CLIENT_ID/portfolio" \
  | python3 "$(dirname "$0")/show_portfolio.py"

printf '\n\033[1;32m✔ הזרימה המלאה עברה\033[0m\n'
