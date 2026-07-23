#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/DrummerIke/AURORA-GUI.git"
BASE="$HOME/AURORA-GUI"
STAMP="$(date +%Y%m%d_%H%M%S)"

if [ -d "$BASE" ] && [ ! -d "$BASE/.git" ]; then
  echo "Сохраняю текущую папку: ${BASE}.backup_${STAMP}"
  cp -a "$BASE" "${BASE}.backup_${STAMP}"
  cd "$BASE"
  git init
  git remote add origin "$REPO"
  git fetch origin main
  git reset --hard origin/main
elif [ -d "$BASE/.git" ]; then
  cd "$BASE"
  git remote set-url origin "$REPO"
  git fetch origin main
  git reset --hard origin/main
else
  git clone "$REPO" "$BASE"
  cd "$BASE"
fi

if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "Не найден модуль venv. Выполни: sudo apt install python3-venv"
  exit 1
fi

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip wheel setuptools
.venv/bin/python -m pip install -r requirements.txt

install_optional() {
  local label="$1"
  shift
  echo "Устанавливаю ${label}..."
  if ! .venv/bin/python -m pip install "$@"; then
    echo "[WARN] ${label} не установлен. Aurora продолжит работать без этого модуля."
  fi
}

install_optional "Sherlock" sherlock-project
install_optional "Maigret" maigret
install_optional "Holehe" holehe
install_optional "Socialscan" socialscan

.venv/bin/python -m py_compile app.py phone_engine.py web_search_engine.py aurora/*.py
chmod +x app.py install.sh run.sh

echo
echo "AURORA установлена в изолированное окружение."
echo "Проверка модулей: http://127.0.0.1:8080/modules"
echo "Запуск: cd ~/AURORA-GUI && ./run.sh"
