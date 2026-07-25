#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${PREFIX:-}" ] || [[ "$PREFIX" != *com.termux* ]]; then
  echo "[WARN] Скрипт рассчитан на Termux; продолжаю с доступным Python."
fi

python -m venv .venv
.venv/bin/python -m pip install --upgrade pip wheel setuptools
.venv/bin/python -m pip install -r requirements.txt

install_optional() {
  local package="$1"
  if ! .venv/bin/python -m pip install "$package"; then
    echo "[WARN] $package не установлен на этой версии Termux. Основной интерфейс продолжит работу."
  fi
}

install_optional sherlock-project
install_optional maigret
install_optional holehe
install_optional socialscan

chmod +x run.sh scripts/*.sh
.venv/bin/python -m py_compile app.py aurora/*.py scripts/doctor.py
.venv/bin/python -m pytest -q
printf '\nГотово. Запуск: cd ~/AURORA-GUI && ./run.sh\nАдрес: http://127.0.0.1:8080\n'
