"""Re-encrypting stored warehouse credentials under a new key (#312)."""

from __future__ import annotations

import subprocess
import sys
import uuid

import pytest
from cryptography.fernet import Fernet

from modules.backend.app.core.credential_crypto import (
    CredentialKeysUnavailable,
    CredentialUndecryptable,
)
from modules.backend.app.models.warehouse_connection import WarehouseConnection
from modules.backend.app.scripts import rotate_warehouse_credentials as command

K0 = Fernet.generate_key().decode()  # a key that is no longer configured
K1 = Fernet.generate_key().decode()  # the old key
K2 = Fernet.generate_key().decode()  # the new key


def _connection(db_session, *, current=None, pending=None, key=K1):
    conn = WarehouseConnection(
        name=f"rot-{uuid.uuid4().hex[:8]}", warehouse_type="snowflake"
    )
    if current is not None:
        conn.set_credentials(current, keys=key)
    if pending is not None:
        conn.set_credentials(pending, pending=True, keys=key)
    db_session.add(conn)
    db_session.commit()
    return conn


def _reload(db_session, conn) -> WarehouseConnection:
    db_session.expire(conn)
    return db_session.get(WarehouseConnection, conn.id)


@pytest.mark.regression
def test_every_token_is_re_encrypted_under_the_first_key(db_session):
    a = _connection(db_session, current=b"a-current", pending=b"a-pending")
    b = _connection(db_session, current=b"b-current")
    none = _connection(db_session)

    report = command.rotate_all(
        db_session, keys=f"{K2},{K1}", connection_ids=[a.id, b.id, none.id]
    )

    assert report.rotated == 3
    assert report.undecryptable == []
    assert report.summary() == "rotated=3 undecryptable=0"
    a, b = _reload(db_session, a), _reload(db_session, b)
    # The new key alone opens every token now ...
    assert a.get_credentials(keys=K2) == b"a-current"
    assert a.get_credentials(pending=True, keys=K2) == b"a-pending"
    assert b.get_credentials(keys=K2) == b"b-current"
    # ... and the old key alone opens none of them.
    with pytest.raises(CredentialUndecryptable):
        a.get_credentials(keys=K1)


@pytest.mark.regression
def test_a_token_no_key_opens_is_left_alone_and_reported(db_session):
    good = _connection(db_session, current=b"good")
    stale = _connection(db_session, current=b"stale", key=K0)
    stale_token = bytes(stale.credentials_ciphertext)

    report = command.rotate_all(
        db_session, keys=f"{K2},{K1}", connection_ids=[good.id, stale.id]
    )

    assert report.rotated == 1
    assert report.undecryptable == [stale.id]
    assert report.summary() == "rotated=1 undecryptable=1"
    assert bytes(_reload(db_session, stale).credentials_ciphertext) == stale_token
    assert _reload(db_session, good).get_credentials(keys=K2) == b"good"


@pytest.mark.parametrize("keys", ["", "not-a-fernet-key"], ids=["absent", "malformed"])
def test_no_usable_keys_changes_nothing(db_session, keys):
    conn = _connection(db_session, current=b"kept")
    token = bytes(conn.credentials_ciphertext)

    with pytest.raises(CredentialKeysUnavailable):
        command.rotate_all(db_session, keys=keys, connection_ids=[conn.id])

    assert bytes(_reload(db_session, conn).credentials_ciphertext) == token


def test_no_keys_refuses_even_with_nothing_to_rotate(db_session):
    with pytest.raises(CredentialKeysUnavailable):
        command.rotate_all(db_session, keys="", connection_ids=[])


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------
def test_main_without_keys_exits_2_and_names_no_key(db_session, monkeypatch, capsys):
    from modules.backend.app import settings as modules_settings

    monkeypatch.setattr(
        modules_settings.settings, "WAREHOUSE_CREDENTIALS_KEYS", "not-a-fernet-key"
    )
    assert command.main([], db=db_session) == command.EXIT_KEYS_UNAVAILABLE
    out = capsys.readouterr()
    assert "not rotated" in out.err
    assert "WAREHOUSE_CREDENTIALS_KEYS" in out.err
    assert "not-a-fernet-key" not in out.err + out.out


def test_main_reports_and_exits_1_on_undecryptable(monkeypatch, capsys):
    stuck = uuid.uuid4()
    monkeypatch.setattr(
        command,
        "rotate_all",
        lambda db: command.RotationReport(rotated=4, undecryptable=[stuck]),
    )
    assert command.main([], db=object()) == command.EXIT_UNDECRYPTABLE
    out = capsys.readouterr()
    assert out.out.strip() == "rotated=4 undecryptable=1"
    assert str(stuck) in out.err


def test_main_exits_0_when_everything_rotated(monkeypatch, capsys):
    monkeypatch.setattr(
        command, "rotate_all", lambda db: command.RotationReport(rotated=2)
    )
    assert command.main([], db=object()) == command.EXIT_OK
    assert capsys.readouterr().out.strip() == "rotated=2 undecryptable=0"


def test_the_documented_command_runs_as_a_module():
    """``python -m modules.backend.app.scripts.rotate_warehouse_credentials``."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "modules.backend.app.scripts.rotate_warehouse_credentials",
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "WAREHOUSE_CREDENTIALS_KEYS" in result.stdout
