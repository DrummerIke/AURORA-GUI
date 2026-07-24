#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip wheel setuptools
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install sherlock-project maigret holehe socialscan || true
if command -v go >/dev/null 2>&1; then go install github.com/projectdiscovery/dnsx/cmd/dnsx@latest || true; fi
