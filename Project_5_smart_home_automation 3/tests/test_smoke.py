import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
from app import app

@pytest.fixture()
def client():
    app.config.update(TESTING=True)
    with app.test_client() as c: yield c

def test_home_requires_login(client): assert client.get('/').status_code == 302
def test_login_page_loads(client): assert client.get('/login').status_code == 200
