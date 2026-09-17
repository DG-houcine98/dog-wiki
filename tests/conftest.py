import os
import sys

os.environ.setdefault('S3_BUCKET', 'test-bucket')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import app as app_module


@pytest.fixture
def mock_db(mocker):
    conn = mocker.MagicMock()
    cur = mocker.MagicMock()
    conn.cursor.return_value = cur
    mocker.patch.object(app_module, 'get_db', return_value=conn)
    return cur


@pytest.fixture
def mock_s3(mocker):
    return mocker.patch.object(app_module, 's3')


@pytest.fixture
def client(mock_db, mock_s3):
    app_module.app.testing = True
    return app_module.app.test_client()
