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


def test_upsert_quotes_values_that_contain_dollar(tmp_path):
    env_path = tmp_path / ".env"
    raw = "scrypt:32768:8:1$SALT$abcdef"
    hash_password.upsert_env_value(str(env_path), "ADMIN_PASSWORD_HASH", raw)
    assert env_path.read_text() == f"ADMIN_PASSWORD_HASH='{raw}'\n"


def test_unquoted_hash_is_not_interpolated(tmp_path, monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("SALT", "SHOULD_NOT_REPLACE")
    raw = "scrypt:32768:8:1$SALT$abcdef"
    env_path = tmp_path / ".env"
    env_path.write_text(f"ADMIN_PASSWORD_HASH={raw}\n")
    from dotenv import load_dotenv
    assert load_dotenv(env_path, override=True, interpolate=False)
    assert os.environ["ADMIN_PASSWORD_HASH"] == raw
