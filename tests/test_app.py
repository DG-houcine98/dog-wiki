import io
import uuid
from datetime import datetime

from PIL import Image

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
    ):
        resp = client.get(path)
        assert resp.status_code == 404
