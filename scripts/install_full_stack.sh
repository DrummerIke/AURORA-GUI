#!/usr/bin/env bash
set -u

BASE="${HOME}/AURORA-GUI"
export PATH="${BASE}/.venv/bin:${HOME}/bin:${HOME}/go/bin:${PATH}"

log() { printf '\n[AURORA] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*"; }

cd "$BASE" || exit 1

log "Installing Python dependencies"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install sherlock-project maigret holehe socialscan ghunt || warn "Some Python tools failed"

if command -v go >/dev/null 2>&1; then
  log "Installing Go tools"
  tools=(
    "github.com/projectdiscovery/dnsx/cmd/dnsx@latest"
    "github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest"
    "github.com/projectdiscovery/httpx/cmd/httpx@latest"
    "github.com/projectdiscovery/katana/cmd/katana@latest"
    "github.com/projectdiscovery/naabu/v2/cmd/naabu@latest"
    "github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest"
    "github.com/tomnomnom/waybackurls@latest"
    "github.com/lc/gau/v2/cmd/gau@latest"
  )
  for package in "${tools[@]}"; do
    log "go install ${package}"
    go install "$package" || warn "Failed: ${package}"
  done
else
  warn "Go is not installed; Go tools were skipped"
fi

if command -v nuclei >/dev/null 2>&1; then
  log "Updating Nuclei templates"
  nuclei -update-templates || warn "Nuclei template update failed"
fi

log "PhoneInfoga note"
warn "PhoneInfoga upstream Go build currently requires missing web/client/dist assets. It is not treated as mandatory."

log "Environment note"
if [ -n "${ANDROID_ROOT:-}" ] || [ -n "${PROOT_TMP_DIR:-}" ] || printf '%s' "${PREFIX:-}" | grep -qi termux; then
  warn "Android/PRoot detected: Naabu raw-socket scanning may remain unavailable. Use a VPS or regular Linux host for that module."
fi

log "Installed tool paths"
for tool in sherlock maigret socialscan holehe ghunt spiderfoot dnsx subfinder httpx katana naabu nuclei waybackurls gau amass gitleaks trufflehog; do
  printf '%-16s %s\n' "$tool" "$(command -v "$tool" 2>/dev/null || echo MISSING)"
done

printf '\nDone. Restart Aurora with:\n  cd ~/AURORA-GUI && ./run.sh\n'
