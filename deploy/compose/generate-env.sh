#!/bin/sh
# deploy/compose/generate-env.sh -- write the .env that compose.yml reads,
# with freshly generated secrets. Run it once, before the first start.
#
#   ./generate-env.sh
#   PUBLIC_BASE_URL=https://experimently.example.com \
#   FIRST_SUPERUSER=you@example.com ./generate-env.sh
#
# It REFUSES to overwrite an existing file. A second run would otherwise rotate
# SECRET_KEY (signing everyone out) and write a new FIRST_SUPERUSER_PASSWORD
# that no longer matches the administrator already in the database, and a new
# POSTGRES_PASSWORD the existing database volume does not accept. To start
# again from nothing, `docker compose down -v` and delete .env first.
#
# Inputs (environment, all optional):
#   ENV_FILE              where to write     (default: .env beside this script)
#   PUBLIC_BASE_URL       the URL people open (default: http://localhost:8080)
#   FIRST_SUPERUSER       the first administrator's email (default: admin@example.com)
#   EXPERIMENTLY_PROFILE  core or full        (default: core)
#
# Needs openssl, or python3 when openssl is absent.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
env_file=${ENV_FILE:-$here/.env}
public_base_url=${PUBLIC_BASE_URL:-http://localhost:8080}
first_superuser=${FIRST_SUPERUSER:-admin@example.com}
profile=${EXPERIMENTLY_PROFILE:-core}

if [ -e "$env_file" ]; then
    echo "$env_file exists; not overwriting it." >&2
    echo "Rerunning would replace the secrets the running install already uses." >&2
    exit 1
fi

case $profile in
    core | full) ;;
    *)
        echo "EXPERIMENTLY_PROFILE must be core or full, got '$profile'." >&2
        exit 1
        ;;
esac

# hex <bytes> / b64 <bytes>: random secrets, from openssl or python3.
if command -v openssl >/dev/null 2>&1; then
    hex() { openssl rand -hex "$1"; }
    b64() { openssl rand -base64 "$1"; }
elif command -v python3 >/dev/null 2>&1; then
    hex() { python3 -c 'import secrets, sys; print(secrets.token_hex(int(sys.argv[1])))' "$1"; }
    b64() { python3 -c 'import base64, secrets, sys; print(base64.b64encode(secrets.token_bytes(int(sys.argv[1]))).decode())' "$1"; }
else
    echo "Need openssl or python3 to generate secrets." >&2
    exit 1
fi

# Generate every value before creating the file, so a failure leaves nothing
# half-written behind.
secret_key=$(hex 32)
audit_hmac_key=$(hex 32)
postgres_password=$(hex 24)
admin_password=$(b64 18)
for value in "$secret_key" "$audit_hmac_key" "$postgres_password" "$admin_password"; do
    if [ -z "$value" ]; then
        echo "Generating a secret failed; nothing was written." >&2
        exit 1
    fi
done

# noclobber makes the create itself refuse an existing file, so two runs
# racing each other cannot both write it; umask keeps it private to you.
umask 077
set -C
cat >"$env_file" <<EOF
# Written by generate-env.sh. Keep this file private and back it up with the
# database: the secrets below cannot be regenerated.
EXPERIMENTLY_PROFILE=$profile
PUBLIC_BASE_URL=$public_base_url
SECRET_KEY=$secret_key
AUDIT_HMAC_KEY=$audit_hmac_key
POSTGRES_PASSWORD=$postgres_password
FIRST_SUPERUSER=$first_superuser
FIRST_SUPERUSER_PASSWORD=$admin_password
EOF

echo "Wrote $env_file."
echo "Sign in at $public_base_url as $first_superuser; the password is FIRST_SUPERUSER_PASSWORD in that file."
