#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/autobili}"
ENV_FILE="${ENV_FILE:-/etc/autobili.env}"
STATE_DIR="${STATE_DIR:-/var/lib/autobili}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this check as root." >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

runuser -u autobili --preserve-environment -- env \
  HOME="${STATE_DIR}" \
  PYTHONPATH="${APP_DIR}" \
  XDG_CACHE_HOME="${STATE_DIR}/.cache" \
  XDG_CONFIG_HOME="${STATE_DIR}/.config" \
  "${APP_DIR}/.venv/bin/python" "${APP_DIR}/deploy/pdf_smoke.py"
