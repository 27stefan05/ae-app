import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hash_password


def test_upsert_creates_new_file(tmp_path):
    env_path = tmp_path / ".env"
    hash_password.upsert_env_value(str(env_path), 'ADMIN_PASSWORD_HASH', 'abc123')
    assert env_path.read_text() == 'ADMIN_PASSWORD_HASH=abc123\n'


def test_upsert_appends_to_existing_file(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text('SECRET_KEY=xyz\n')
    hash_password.upsert_env_value(str(env_path), 'ADMIN_PASSWORD_HASH', 'abc123')
    assert env_path.read_text() == 'SECRET_KEY=xyz\nADMIN_PASSWORD_HASH=abc123\n'


def test_upsert_replaces_existing_value(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text('ADMIN_PASSWORD_HASH=old\nSECRET_KEY=xyz\n')
    hash_password.upsert_env_value(str(env_path), 'ADMIN_PASSWORD_HASH', 'new123')
    assert env_path.read_text() == 'ADMIN_PASSWORD_HASH=new123\nSECRET_KEY=xyz\n'


def test_upsert_handles_missing_trailing_newline(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text('SECRET_KEY=xyz')
    hash_password.upsert_env_value(str(env_path), 'ADMIN_PASSWORD_HASH', 'abc123')
    assert env_path.read_text() == 'SECRET_KEY=xyz\nADMIN_PASSWORD_HASH=abc123\n'
