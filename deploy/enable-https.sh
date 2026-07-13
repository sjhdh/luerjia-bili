#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${DOMAIN:-autobili.luerjia.art}"
APP_DIR="${APP_DIR:-/opt/autobili}"
CERTBOT_DIR="${CERTBOT_DIR:-/opt/autobili-certbot}"
ACME_ROOT="${ACME_ROOT:-/var/www/autobili-acme}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.cloud.tencent.com/pypi/simple}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.12 || command -v python3.11 || command -v python3)}"
install -d -o root -g root -m 0755 "${ACME_ROOT}/.well-known/acme-challenge"

"${PYTHON_BIN}" -m venv "${CERTBOT_DIR}"
"${CERTBOT_DIR}/bin/python" -m pip install --index-url "${PIP_INDEX_URL}" --upgrade pip
"${CERTBOT_DIR}/bin/python" -m pip install --index-url "${PIP_INDEX_URL}" "certbot>=3,<5"

"${CERTBOT_DIR}/bin/certbot" certonly \
  --webroot --webroot-path "${ACME_ROOT}" \
  --domain "${DOMAIN}" \
  --non-interactive --agree-tos --register-unsafely-without-email \
  --keep-until-expiring

if [[ -d /www/server/panel/vhost/nginx ]]; then
  VHOST_PATH="/www/server/panel/vhost/nginx/${DOMAIN}.conf"
elif [[ -d /etc/nginx/sites-available ]]; then
  VHOST_PATH="/etc/nginx/sites-available/autobili.conf"
else
  echo "Unsupported nginx configuration layout." >&2
  exit 1
fi

install -o root -g root -m 0600 "${APP_DIR}/deploy/nginx-autobili-ssl.conf" "${VHOST_PATH}"
nginx -t
nginx -s reload

install -o root -g root -m 0644 "${APP_DIR}/deploy/autobili-cert-renew.service" \
  /etc/systemd/system/autobili-cert-renew.service
install -o root -g root -m 0644 "${APP_DIR}/deploy/autobili-cert-renew.timer" \
  /etc/systemd/system/autobili-cert-renew.timer
systemctl daemon-reload
systemctl enable --now autobili-cert-renew.timer

curl --fail --silent --show-error "https://${DOMAIN}/api/v1/health"
echo
echo "HTTPS enabled for ${DOMAIN}."
