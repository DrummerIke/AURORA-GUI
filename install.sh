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

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m py_compile app.py phone_engine.py web_search_engine.py
chmod +x app.py install.sh

echo
echo "AURORA установлена. Запуск:"
echo "cd ~/AURORA-GUI && python3 app.py"
