#!/bin/bash
# Smoke test of the core flow against a RUNNING Tempo (read-only: no data is created or changed).
#   TEMPO_URL=https://tempo.example.com TEMPO_USER=name TEMPO_PASSWORD=... scripts/smoke.sh
# Or put url=, username=, password= lines in a file and pass TEMPO_CREDENTIALS_FILE=path (keeps the password out of shell history).
set -uo pipefail
if [ -n "${TEMPO_CREDENTIALS_FILE:-}" ]; then
  TEMPO_URL="${TEMPO_URL:-$(grep '^url=' "$TEMPO_CREDENTIALS_FILE" | cut -d= -f2-)}"
  TEMPO_USER="${TEMPO_USER:-$(grep '^username=' "$TEMPO_CREDENTIALS_FILE" | cut -d= -f2-)}"
  TEMPO_PASSWORD="${TEMPO_PASSWORD:-$(grep '^password=' "$TEMPO_CREDENTIALS_FILE" | cut -d= -f2-)}"
fi
: "${TEMPO_URL:?set TEMPO_URL}" "${TEMPO_USER:?set TEMPO_USER}" "${TEMPO_PASSWORD:?set TEMPO_PASSWORD}"
B="${TEMPO_URL%/}/v1"; JAR="$(mktemp)"; trap 'rm -f "$JAR"' EXIT; fail=0
ok()  { printf '  ok    %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1"; fail=1; }
code() { curl -s -o /dev/null -w '%{http_code}' -b "$JAR" "$@"; }

echo "Smoke test: $TEMPO_URL"
[ "$(curl -s -o /dev/null -w '%{http_code}' "${TEMPO_URL%/}/readyz")" = 200 ] && ok "readyz (database connected)" || bad "readyz"
[ "$(curl -s -o /dev/null -w '%{http_code}' "${TEMPO_URL%/}/")" = 200 ] && ok "console loads" || bad "console"
[ "$(code "$B/me/access")" = 401 ] && ok "anonymous request is refused" || bad "anonymous request was not refused"
body=$(printf '{"username":"%s","password":"%s"}' "$TEMPO_USER" "$TEMPO_PASSWORD")
r=$(curl -s -c "$JAR" -X POST "$B/auth/login" -H 'content-type: application/json' -d "$body")
echo "$r" | grep -q '"signed_in"' && ok "password sign-in" || { bad "password sign-in ($r)"; echo "stopping: cannot continue without a session"; exit 1; }
site=$(curl -s -b "$JAR" "$B/sites" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[0]["site_id"] if d else "")' 2>/dev/null)
[ -n "$site" ] && ok "sites visible (first: $site)" || { bad "no sites visible"; exit 1; }
for p in "me/access" "notifications" "sites/$site/overview" "sites/$site/demand" "sites/$site/rosters" "sites/$site/roster" "sites/$site/attendance/live" "sites/$site/timesheets" "sites/$site/reports/variance" "imports/status" "setup/checklist" "imports/contracts"; do
  c=$(code "$B/$p"); [ "$c" = 200 ] && ok "GET /$p" || bad "GET /$p -> $c"
done
c=$(curl -s -b "$JAR" -o /dev/null -w '%{http_code}' -X POST "$B/auth/logout" -H "X-CSRF-Token: $(grep tempo_csrf "$JAR" | awk '{print $7}')"); [ "$c" = 200 ] && ok "sign-out" || bad "sign-out -> $c"
[ $fail = 0 ] && echo "SMOKE PASSED" || { echo "SMOKE FAILED"; exit 1; }
