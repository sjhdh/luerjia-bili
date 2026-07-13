#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/autobili}"
ENV_FILE="${ENV_FILE:-/etc/autobili.env}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this check as root." >&2
  exit 1
fi

restart_service() {
  systemctl start autobili.service
}

systemctl stop autobili.service
trap restart_service EXIT

set -a
source "${ENV_FILE}"
set +a

runuser -u autobili --preserve-environment -- env \
  PYTHONPATH="${APP_DIR}" \
  /usr/bin/time -v "${APP_DIR}/.venv/bin/python" "${APP_DIR}/deploy/model_smoke.py"
