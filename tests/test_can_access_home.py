import os, sys, sqlite3
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from domain import can_access_home


@pytest.fixture
def db():
    conn = sqlite3.connect(':memory:')
    conn.executescript(open(os.path.join(ROOT, 'schema.sql'), encoding='utf-8').read())
    conn.executescript(open(os.path.join(ROOT, 'seed.sql'), encoding='utf-8').read())
    yield conn
    conn.close()


def test_owner_can_access_own_home(db):
    assert can_access_home(db, 1, 1) is not None

def test_member_can_access_her_home(db):
    assert can_access_home(db, 2, 1) is not None

def test_member_cannot_access_other_home(db):
    assert can_access_home(db, 2, 2) is None

def test_installer_with_no_membership_cannot_access(db):
    assert can_access_home(db, 3, 1) is None

def test_inactive_membership_cannot_access(db):
    db.execute("UPDATE memberships SET status='INACTIVE' WHERE user_id=2")
    assert can_access_home(db, 2, 1) is None
