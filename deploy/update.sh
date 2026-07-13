#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/autobili}"
STATE_DIR="${STATE_DIR:-/var/lib/autobili}"
SERVICE_USER="${SERVICE_USER:-autobili}"
ENV_FILE="${ENV_FILE:-/etc/autobili.env}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this updater as root." >&2
  exit 1
fi

cd "${APP_DIR}"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git pull --ff-only
else
  echo "Git metadata is absent; updating the source already staged in ${APP_DIR}."
fi
"${APP_DIR}/.venv/bin/python" -m pip install "${APP_DIR}"
MIGRATION_DATA_DIR="${STATE_DIR}/data"
MIGRATION_DATABASE_URL=""
if [[ -f "${ENV_FILE}" ]]; then
  MIGRATION_DATA_DIR="$(awk -F= '$1 == "DATA_DIR" { sub(/^[^=]*=/, ""); print; exit }' "${ENV_FILE}")"
  MIGRATION_DATABASE_URL="$(awk -F= '$1 == "DATABASE_URL" { sub(/^[^=]*=/, ""); print; exit }' "${ENV_FILE}")"
fi
MIGRATION_DATA_DIR="${MIGRATION_DATA_DIR:-${STATE_DIR}/data}"
if [[ -n "${MIGRATION_DATABASE_URL}" ]]; then
  runuser -u "${SERVICE_USER}" -- env DATA_DIR="${MIGRATION_DATA_DIR}" DATABASE_URL="${MIGRATION_DATABASE_URL}" \
    "${APP_DIR}/.venv/bin/python" -m alembic upgrade head
else
  runuser -u "${SERVICE_USER}" -- env DATA_DIR="${MIGRATION_DATA_DIR}" \
    "${APP_DIR}/.venv/bin/python" -m alembic upgrade head
fi

if command -v npm >/dev/null 2>&1; then
  npm --prefix frontend ci
  npm --prefix frontend run build
fi
if [[ -d "${APP_DIR}/frontend/dist" ]]; then
  find "${APP_DIR}/frontend/dist" -type d -exec chmod 0755 {} +
  find "${APP_DIR}/frontend/dist" -type f -exec chmod 0644 {} +
fi

if [[ ! -x /usr/bin/google-chrome-stable ]]; then
  runuser -u autobili -- env \
    HOME="${STATE_DIR}" \
    PLAYWRIGHT_BROWSERS_PATH="${STATE_DIR}/playwright" \
    "${APP_DIR}/.venv/bin/python" -m playwright install chromium
fi

systemctl restart autobili.service
curl --fail --retry 20 --retry-delay 1 --retry-connrefused \
  http://127.0.0.1:8000/api/v1/health
