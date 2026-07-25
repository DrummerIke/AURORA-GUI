#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "Виртуальное окружение не найдено. Запусти: bash install.sh"
  exit 1
fi

export PATH="$PWD/.venv/bin:$PATH"
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi
exec .venv/bin/python app.py
