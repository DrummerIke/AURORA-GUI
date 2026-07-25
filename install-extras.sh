#!/usr/bin/env bash
set -euo pipefail

BASE="$HOME/AURORA-GUI"
VENV="$BASE/.venv"

cd "$BASE"

if [ ! -x "$VENV/bin/python" ]; then
  echo "Сначала запусти: bash install.sh"
  exit 1
fi

"$VENV/bin/python" -m pip install --upgrade pip setuptools wheel

install_optional() {
  local package="$1"
  echo
  echo "Устанавливаю: $package"
  if ! "$VENV/bin/python" -m pip install "$package"; then
    echo "[WARN] Не удалось установить $package. Остальные модули продолжат работу."
  fi
}

install_phoneinfoga() {
  echo
  echo "Устанавливаю: PhoneInfoga"
  if [ -x "$VENV/bin/phoneinfoga" ]; then
    echo "PhoneInfoga уже установлен."
    return
  fi
  if ! command -v curl >/dev/null 2>&1; then
    echo "[WARN] curl не найден, PhoneInfoga пропущен."
    return
  fi

  local tmpdir
  tmpdir="$(mktemp -d)"
  if (
    cd "$tmpdir"
    bash <(curl -fsSL https://raw.githubusercontent.com/sundowndev/phoneinfoga/master/support/scripts/install)
  ); then
    if [ -x "$tmpdir/phoneinfoga" ]; then
      install -m 755 "$tmpdir/phoneinfoga" "$VENV/bin/phoneinfoga"
      echo "PhoneInfoga установлен в $VENV/bin/phoneinfoga"
    else
      echo "[WARN] Установщик завершился, но бинарник PhoneInfoga не найден."
    fi
  else
    echo "[WARN] Не удалось установить PhoneInfoga для этой архитектуры."
  fi
  rm -rf "$tmpdir"
}

install_optional "sherlock-project"
install_optional "maigret"
install_optional "holehe"
install_phoneinfoga

cat > "$BASE/run.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/AURORA-GUI"
export PATH="$HOME/AURORA-GUI/.venv/bin:$HOME/go/bin:$PATH"
exec "$HOME/AURORA-GUI/.venv/bin/python" app.py
EOF

chmod +x "$BASE/run.sh" "$BASE/install-extras.sh"

printf '\nУстановленные модули:\n'
for tool in sherlock maigret holehe phoneinfoga; do
  if [ -x "$VENV/bin/$tool" ] || command -v "$tool" >/dev/null 2>&1; then
    printf '  READY   %s\n' "$tool"
  else
    printf '  MISSING %s\n' "$tool"
  fi
done

printf '\nГотово. Запуск:\n  cd ~/AURORA-GUI && ./run.sh\n'
