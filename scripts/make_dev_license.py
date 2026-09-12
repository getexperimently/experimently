#!/usr/bin/env python3
"""Mint a **development** enterprise licence so the EE path can be exercised locally.

    python scripts/make_dev_license.py --features hipaa,sso,warehouse

It generates an Ed25519 key pair (or reuses the one it generated last time),
signs a licence with the claims ``backend/app/core/license.py`` expects, and
prints the two environment variables you need::

    EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY   the verifying key, PEM
    EXPERIMENTLY_LICENSE_KEY              the signed licence

The licence is minted with ``kid="dev"``.  The verifier trusts that ``kid``
**only** when ``ENVIRONMENT`` is ``development`` or ``test``; a dev licence
cannot unlock a staging or production deployment no matter how the
environment is configured.

SECURITY -- read before running
-------------------------------
* The private key is written **outside the repository**, to
  ``~/.experimently/dev_license_ed25519_private.pem`` (override with
  ``--private-key``), mode 0600.  Never move it into the working tree, never
  commit it, never paste it into an issue.  There is no reason for a private
  key to exist anywhere under version control.
* This script signs **development** licences only.  Production licences are
  signed out-of-band by the release process, with a signing key that lives in
  a secrets manager / HSM and never touches a developer machine.  The
  resulting public key is added to ``EMBEDDED_PUBLIC_KEYS`` in
  ``backend/app/core/license.py`` under a dated ``kid``; rotating a key means
  adding an entry, not changing the verifier.
* Anyone holding the printed private key can mint licences that this checkout
  accepts.  Delete it when you are done: ``rm ~/.experimently/*.pem``.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DEFAULT_PRIVATE_KEY = Path.home() / ".experimently" / "dev_license_ed25519_private.pem"
DEV_KID = "dev"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def load_or_create_private_key(path: Path, *, force_new: bool) -> Ed25519PrivateKey:
    """Return the signing key, generating and persisting one if needed."""
    # The repository guard comes first, before the reuse branch: a key that is
    # already inside the working tree is the situation the guard exists to
    # prevent, and loading it silently would keep signing with a key one
    # `git add -A` away from being published.
    if path.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise SystemExit(f"Refusing to use a private key inside the repository: {path}")

    if path.exists() and not force_new:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise SystemExit(f"{path} is not an Ed25519 private key")
        _warn_if_readable_by_others(path)
        return key

    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    # Create with 0600 before any bytes land on disk.  The mode argument only
    # applies when open() actually creates the file, so `--new-key` over an
    # existing 0644 key would otherwise leave it 0644: fchmod the descriptor
    # too, while it is still empty.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(pem)
    return key


def _warn_if_readable_by_others(path: Path) -> None:
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        print(
            f"# WARNING: {path} is mode {mode:04o}; a signing key should be 0600.",
            file=sys.stderr,
        )


def sign_license(private_key: Ed25519PrivateKey, claims: dict) -> str:
    """Produce ``base64url(claims_json).base64url(signature)``.

    The signature covers the ASCII bytes of the *encoded* claims segment, so a
    verifier never has to reproduce this JSON spelling byte for byte.
    """
    claims_segment = _b64url(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = private_key.sign(claims_segment.encode("ascii"))
    return f"{claims_segment}.{_b64url(signature)}"


def build_claims(args: argparse.Namespace) -> dict:
    now = datetime.now(timezone.utc)
    issued = int(now.timestamp())
    features = [f.strip() for f in args.features.split(",") if f.strip()]
    return {
        "customer": args.customer,
        "plan": args.plan,
        "features": features,
        "iat": issued,
        "nbf": int((now + timedelta(days=args.not_before_days)).timestamp()),
        "exp": int((now + timedelta(days=args.days)).timestamp()),
        "kid": DEV_KID,
        # Per-licence serial. Every licence gets one so a single customer can
        # be cut off without revoking every licence the same key signed; a
        # licence issued without it can only be revoked at `kid` granularity.
        "jti": args.jti or uuid.uuid4().hex,
        "grace_days": args.grace_days,
        "max_seats": args.max_seats,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mint a development enterprise licence (never for production).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--features",
        default="*",
        help="comma-separated feature names, or '*' for all (default: '*')",
    )
    parser.add_argument("--customer", default="Local Development")
    parser.add_argument("--plan", default="enterprise")
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="days until exp (may be negative to "
        "mint an already-expired licence for testing the grace/read-only windows)",
    )
    parser.add_argument(
        "--not-before-days",
        type=int,
        default=0,
        help="offset for nbf; positive mints a not-yet-valid licence",
    )
    parser.add_argument(
        "--jti",
        default=None,
        help="licence serial (default: a fresh uuid4 hex); record it, because "
        "revoking one licence means adding this value to REVOKED_JTIS",
    )
    parser.add_argument("--grace-days", type=int, default=14)
    parser.add_argument("--max-seats", type=int, default=25)
    parser.add_argument(
        "--private-key",
        type=Path,
        default=DEFAULT_PRIVATE_KEY,
        help=f"where the signing key lives (default: {DEFAULT_PRIVATE_KEY})",
    )
    parser.add_argument(
        "--new-key",
        action="store_true",
        help="generate a fresh key pair, overwriting the existing private key",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help=(
            "also append the two variables to this env file. Use `.env.dev` for "
            "`make dev` (DevSettings reads it) and `.env` for `docker compose` "
            "(compose reads it and passes the variables to the api service)"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    private_key = load_or_create_private_key(args.private_key, force_new=args.new_key)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    claims = build_claims(args)
    license_key = sign_license(private_key, claims)

    expires = datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat()
    print(f"# development licence, kid={DEV_KID}, expires {expires}")
    print(f"# private key: {args.private_key} (keep it out of the repository)")
    print(f"# claims: {json.dumps(claims, sort_keys=True)}")
    print()
    print("# Public key, in the form backend/app/core/license.py wants:")
    print(f"EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY='{public_pem.strip()}'")
    print()
    print(f"EXPERIMENTLY_LICENSE_KEY={license_key}")
    print()
    print("# For EMBEDDED_PUBLIC_KEYS (production keys only, never this one):")
    print(f'#   "{DEV_KID}": """{public_pem.strip()}""",')

    if args.env_file:
        one_line = public_pem.strip().replace("\n", "\\n")
        with args.env_file.open("a", encoding="utf-8") as handle:
            handle.write(f'\nEXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY="{one_line}"\n')
            handle.write(f"EXPERIMENTLY_LICENSE_KEY={license_key}\n")
        print(f"\n# appended to {args.env_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
