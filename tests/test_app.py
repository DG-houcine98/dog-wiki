import io
import uuid
from datetime import datetime

import pytest
from PIL import Image

import app as app_module
from app import _breed_to_key, _to_webp_bytes


def _png_bytes():
    img = Image.new('RGB', (4, 4), color='red')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


class FakeUpload:
    def __init__(self):
        self.stream = _png_bytes()


def test_breed_to_key_basic():
    assert _breed_to_key('Golden Retriever') == 'dogs/GoldenRetriever.webp'


def test_breed_to_key_strips_punctuation_and_whitespace():
    assert _breed_to_key('  shih-tzu!! ') == 'dogs/Shihtzu.webp'


def test_to_webp_bytes_converts_image():
    buf = _to_webp_bytes(FakeUpload())
    img = Image.open(buf)
    assert img.format == 'WEBP'


def test_to_webp_bytes_converts_rgba_image():
    img = Image.new('RGBA', (4, 4), color=(255, 0, 0, 128))
    raw = io.BytesIO()
    img.save(raw, format='PNG')
    raw.seek(0)

    class Upload:
        stream = raw

    buf = _to_webp_bytes(Upload())
    assert Image.open(buf).format == 'WEBP'


def test_get_db_uses_env_config(mocker):
    mock_connect = mocker.patch.object(app_module.psycopg2, 'connect')
    app_module.get_db()
    mock_connect.assert_called_once_with(
        host=app_module.DB_HOST,
        dbname=app_module.DB_NAME,
        user=app_module.DB_USER,
        password=app_module.DB_PASSWORD,
    )


def test_init_db_succeeds_immediately(mocker):
    conn = mocker.MagicMock()
    mocker.patch.object(app_module, 'get_db', return_value=conn)
    app_module.init_db()
    conn.cursor.return_value.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_init_db_gives_up_after_retries(mocker):
    mocker.patch.object(app_module, 'get_db', side_effect=app_module.psycopg2.OperationalError)
    mocker.patch.object(app_module.time, 'sleep')
    with pytest.raises(RuntimeError):
        app_module.init_db()


def test_index(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert resp.get_json()['message']


def test_health(client):
    resp = client.get('/health')
    assert resp.status_code == 200
    assert resp.get_json() == {'status': 'ok'}


def test_list_dogs(client, mock_db):
    dog_id = uuid.uuid4()
    mock_db.fetchall.return_value = [
        (dog_id, 'Beagle', 'friendly', 'dogs/Beagle.webp', datetime(2024, 1, 1)),
    ]
    resp = client.get('/dogs')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body[0]['breed'] == 'Beagle'
    assert body[0]['photo_url'] == f'/photos/{dog_id}'


def test_get_dog_not_found(client, mock_db):
    mock_db.fetchone.return_value = None
    resp = client.get(f'/dogs/{uuid.uuid4()}')
    assert resp.status_code == 404


def test_get_dog_found(client, mock_db):
    dog_id = uuid.uuid4()
    mock_db.fetchone.return_value = (
        dog_id, 'Poodle', 'curly', None, datetime(2024, 1, 1),
    )
    resp = client.get(f'/dogs/{dog_id}')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['breed'] == 'Poodle'
    assert body['photo_url'] is None


def test_create_dog_requires_breed(client):
    resp = client.post('/dogs', data={})
    assert resp.status_code == 400


def test_create_dog_success(client, mock_db, mock_s3):
    resp = client.post('/dogs', data={'breed': 'Pug', 'description': 'small'})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body['breed'] == 'Pug'
    mock_db.execute.assert_called()


def test_create_dog_with_photo_uploads_to_s3(client, mock_db, mock_s3):
    data = {
        'breed': 'Corgi',
        'photo': (_png_bytes(), 'dog.png'),
    }
    resp = client.post('/dogs', data=data, content_type='multipart/form-data')
    assert resp.status_code == 201
    mock_s3.upload_fileobj.assert_called_once()


def test_get_photo_not_found(client, mock_db):
    mock_db.fetchone.return_value = None
    resp = client.get(f'/photos/{uuid.uuid4()}')
    assert resp.status_code == 404


def test_get_photo_found(client, mock_db, mock_s3, mocker):
    mock_db.fetchone.return_value = ('dogs/Beagle.webp',)
    mock_s3.get_object.return_value = {
        'Body': mocker.Mock(read=mocker.Mock(return_value=b'imgdata')),
        'ContentType': 'image/webp',
    }
    resp = client.get(f'/photos/{uuid.uuid4()}')
    assert resp.status_code == 200
    assert resp.data == b'imgdata'


def test_update_dog_replaces_photo(client, mock_db, mock_s3):
    dog_id = uuid.uuid4()
    mock_db.fetchone.return_value = (dog_id, 'dogs/OldPhoto.webp')
    data = {
        'breed': 'Corgi',
        'photo': (_png_bytes(), 'new.png'),
    }
    resp = client.put(f'/dogs/{dog_id}', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200
    mock_s3.upload_fileobj.assert_called_once()


def test_update_dog_not_found(client, mock_db):
    mock_db.fetchone.return_value = None
    resp = client.put(f'/dogs/{uuid.uuid4()}', data={'breed': 'Husky'})
    assert resp.status_code == 404


def test_update_dog_requires_breed(client, mock_db):
    mock_db.fetchone.return_value = (uuid.uuid4(), None)
    resp = client.put(f'/dogs/{uuid.uuid4()}', data={})
    assert resp.status_code == 400


def test_update_dog_success(client, mock_db, mock_s3):
    dog_id = uuid.uuid4()
    mock_db.fetchone.return_value = (dog_id, None)
    resp = client.put(f'/dogs/{dog_id}', data={'breed': 'Husky', 'description': 'fluffy'})
    assert resp.status_code == 200
    assert resp.get_json()['breed'] == 'Husky'


def test_delete_dog_not_found(client, mock_db):
    mock_db.fetchone.return_value = None
    resp = client.delete(f'/dogs/{uuid.uuid4()}')
    assert resp.status_code == 404


def test_delete_dog_success(client, mock_db, mock_s3):
    mock_db.fetchone.return_value = ('dogs/Beagle.webp',)
    resp = client.delete(f'/dogs/{uuid.uuid4()}')
    assert resp.status_code == 200
    assert resp.get_json() == {'ok': True}


def test_delete_dog_swallows_s3_errors(client, mock_db, mock_s3):
    mock_db.fetchone.return_value = ('dogs/Beagle.webp',)
    mock_s3.delete_object.side_effect = Exception('boom')
    resp = client.delete(f'/dogs/{uuid.uuid4()}')
    assert resp.status_code == 200


def test_vuln_endpoints_disabled_by_default(client):
    for path in (
        '/vuln/crash/divide-by-zero',
        '/vuln/crash/exception',
        '/vuln/crash/oom',
        '/vuln/crash/slow',
        '/vuln/crash/cpu',
        '/vuln/lfi',
        '/vuln/sqli',
        '/vuln/cmd',
        '/vuln/cws/passwd-write',
        '/vuln/cws/spawn-shell',
        '/vuln/cws/discovery',
        '/vuln/cws/crypto-miner',
        '/vuln/cws/reverse-shell',
        '/vuln/cws/ld-preload',
        '/vuln/cws/kernel-module',
        '/vuln/ssrf',
    ):
        resp = client.get(path)
        assert resp.status_code == 404


def test_login_requires_username_and_password(client):
    resp = client.post('/auth/login', json={'username': 'demo'})
    assert resp.status_code == 400


def test_login_invalid_credentials(client):
    resp = client.post('/auth/login', json={'username': 'demo', 'password': 'wrong'})
    assert resp.status_code == 401


def test_login_unknown_user(client):
    resp = client.post('/auth/login', json={'username': 'nobody', 'password': 'x'})
    assert resp.status_code == 401


def test_login_success_and_me(client):
    resp = client.post('/auth/login', json={'username': 'demo', 'password': 'demo'})
    assert resp.status_code == 200
    token = resp.get_json()['token']

    me = client.get('/auth/me', headers={'Authorization': f'Bearer {token}'})
    assert me.status_code == 200
    assert me.get_json()['user'] == 'demo'


def test_me_requires_valid_token(client):
    resp = client.get('/auth/me', headers={'Authorization': 'Bearer not-a-real-token'})
    assert resp.status_code == 401

    resp = client.get('/auth/me')
    assert resp.status_code == 401


def test_logout_invalidates_token(client):
    login = client.post('/auth/login', json={'username': 'admin', 'password': 'admin123'})
    token = login.get_json()['token']

    logout = client.post('/auth/logout', headers={'Authorization': f'Bearer {token}'})
    assert logout.status_code == 200
    assert logout.get_json() == {'ok': True}

    me = client.get('/auth/me', headers={'Authorization': f'Bearer {token}'})
    assert me.status_code == 401


def test_logout_unknown_token_is_a_noop(client):
    resp = client.post('/auth/logout', headers={'Authorization': 'Bearer unknown'})
    assert resp.status_code == 200
