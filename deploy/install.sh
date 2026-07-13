#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/autobili}"
STATE_DIR="${STATE_DIR:-/var/lib/autobili}"
SERVICE_USER="${SERVICE_USER:-autobili}"
ENV_FILE="${ENV_FILE:-/etc/autobili.env}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.cloud.tencent.com/pypi/simple}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi

if [[ ! -f "${SOURCE_DIR}/pyproject.toml" ]]; then
  echo "Run deploy/install.sh from a complete source checkout." >&2
  exit 1
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir "${STATE_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

install -d -o root -g root -m 0755 "${APP_DIR}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 0750 \
  "${STATE_DIR}" "${STATE_DIR}/data" "${STATE_DIR}/model-cache" "${STATE_DIR}/playwright"

if [[ "${SOURCE_DIR}" != "${APP_DIR}" ]]; then
  tar -C "${SOURCE_DIR}" \
    --exclude=.git --exclude=.venv --exclude=data --exclude=frontend/node_modules \
    -cf - . | tar -C "${APP_DIR}" -xf -
fi

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.12 || command -v python3.11 || command -v python3 || true)}"
if [[ -z "${PYTHON_BIN}" ]]; then
  echo "Python 3.11 or newer is required." >&2
  exit 1
fi
"${PYTHON_BIN}" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"Python 3.11 or newer is required; found {sys.version.split()[0]}")
PY

if [[ ! -s "${ENV_FILE}" ]]; then
  GENERATED_PASSWORD="$("${PYTHON_BIN}" -c 'import secrets; print(secrets.token_hex(18))')"
  TEMP_ENV="$(mktemp)"
  awk -v password="${GENERATED_PASSWORD}" \
    '$0 == "ADMIN_PASSWORD=" { print "ADMIN_PASSWORD=" password; next } { print }' \
    "${APP_DIR}/deploy/autobili.env.example" > "${TEMP_ENV}"
  install -o root -g "${SERVICE_USER}" -m 0640 "${TEMP_ENV}" "${ENV_FILE}"
  rm -f "${TEMP_ENV}"
  echo "Generated private access credentials:"
  echo "  username: operator"
  echo "  password: ${GENERATED_PASSWORD}"
fi

if ! grep -Eq '^ADMIN_PASSWORD=.+$' "${ENV_FILE}"; then
  echo "Set a non-empty ADMIN_PASSWORD in ${ENV_FILE}." >&2
  exit 2
fi

if [[ ! -f "${APP_DIR}/frontend/dist/index.html" ]]; then
  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo "frontend/dist is missing; install Node.js 20+ and build the frontend before installing." >&2
    exit 1
  fi
  NODE_MAJOR="$(node -p 'Number(process.versions.node.split(`.`)[0])')"
  if (( NODE_MAJOR < 20 )); then
    echo "Node.js 20 or newer is required to build the frontend." >&2
    exit 1
  fi
  npm --prefix "${APP_DIR}/frontend" ci
  npm --prefix "${APP_DIR}/frontend" run build
fi
find "${APP_DIR}/frontend/dist" -type d -exec chmod 0755 {} +
find "${APP_DIR}/frontend/dist" -type f -exec chmod 0644 {} +

"${PYTHON_BIN}" -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install --index-url "${PIP_INDEX_URL}" --upgrade pip
if [[ "$(uname -s)" == "Linux" ]]; then
  "${APP_DIR}/.venv/bin/python" -m pip install \
    --index-url https://download.pytorch.org/whl/cpu "torch>=2.5,<3"
fi
"${APP_DIR}/.venv/bin/python" -m pip install --index-url "${PIP_INDEX_URL}" "${APP_DIR}"

MIGRATION_DATA_DIR="$(awk -F= '$1 == "DATA_DIR" { sub(/^[^=]*=/, ""); print; exit }' "${ENV_FILE}")"
MIGRATION_DATABASE_URL="$(awk -F= '$1 == "DATABASE_URL" { sub(/^[^=]*=/, ""); print; exit }' "${ENV_FILE}")"
MIGRATION_DATA_DIR="${MIGRATION_DATA_DIR:-${STATE_DIR}/data}"
if [[ -n "${MIGRATION_DATABASE_URL}" ]]; then
  runuser -u "${SERVICE_USER}" -- env DATA_DIR="${MIGRATION_DATA_DIR}" DATABASE_URL="${MIGRATION_DATABASE_URL}" \
    "${APP_DIR}/.venv/bin/python" -m alembic upgrade head
else
  runuser -u "${SERVICE_USER}" -- env DATA_DIR="${MIGRATION_DATA_DIR}" \
    "${APP_DIR}/.venv/bin/python" -m alembic upgrade head
fi

if command -v apt-get >/dev/null 2>&1; then
  "${APP_DIR}/.venv/bin/python" -m playwright install-deps chromium
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y \
    alsa-lib atk at-spi2-atk cairo cups-libs gtk3 libdrm libX11 libXcomposite \
    libXdamage libXext libXfixes libXi libXrandr libXtst libxcb libxkbcommon \
    mesa-libgbm nspr nss pango liberation-fonts
  if [[ ! -x /usr/bin/google-chrome-stable ]]; then
    dnf install -y \
      https://mirrors.aliyun.com/google-chrome/google-chrome-stable_current_x86_64.rpm
  fi
fi
if [[ ! -x /usr/bin/google-chrome-stable ]]; then
  runuser -u "${SERVICE_USER}" -- env \
    HOME="${STATE_DIR}" \
    PLAYWRIGHT_BROWSERS_PATH="${STATE_DIR}/playwright" \
    "${APP_DIR}/.venv/bin/python" -m playwright install chromium
fi

install -o root -g root -m 0644 "${APP_DIR}/deploy/autobili.service" \
  /etc/systemd/system/autobili.service
systemctl daemon-reload
systemctl enable --now autobili.service

install -d -o root -g root -m 0755 /var/www/autobili-acme/.well-known/acme-challenge
if [[ -d /www/server/panel/vhost/nginx ]]; then
  install -o root -g root -m 0600 "${APP_DIR}/deploy/nginx-autobili.conf" \
    /www/server/panel/vhost/nginx/autobili.luerjia.art.conf
  nginx -t
  /etc/rc.d/init.d/nginx reload
elif [[ -d /etc/nginx/sites-available && -d /etc/nginx/sites-enabled ]]; then
  install -o root -g root -m 0644 "${APP_DIR}/deploy/nginx-autobili.conf" \
    /etc/nginx/sites-available/autobili.conf
  ln -sfn /etc/nginx/sites-available/autobili.conf /etc/nginx/sites-enabled/autobili.conf
  nginx -t
  systemctl reload nginx
else
  echo "nginx uses a non-standard layout; install deploy/nginx-autobili.conf in its vhost directory." >&2
fi

curl --fail --silent --show-error --retry 20 --retry-delay 1 --retry-connrefused \
  http://127.0.0.1:8000/api/v1/health
echo
echo "Autobili service installed. Run deploy/enable-https.sh after HTTP verification."
