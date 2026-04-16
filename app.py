import io
import os
import time
import uuid

import boto3
import psycopg2
from flask import Flask, jsonify, request, send_file

app = Flask(__name__)

S3_BUCKET = os.environ.get('S3_BUCKET')
AWS_REGION = os.environ.get('AWS_REGION', 'eu-west-2')
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
        ext = photo.filename.rsplit('.', 1)[-1] if '.' in photo.filename else 'jpg'
        photo_key = f'dogs/{dog_id}.{ext}'
        s3.upload_fileobj(
            photo, S3_BUCKET, photo_key,
            ExtraArgs={'ContentType': photo.content_type},
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


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8080)
