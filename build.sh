#!/usr/bin/env bash
# Builds a standalone app for the current OS/architecture into dist/.
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv .venv-build
.venv-build/bin/python -m pip install --upgrade pip
.venv-build/bin/python -m pip install -r requirements-build.txt
.venv-build/bin/pyinstaller --noconfirm nestcal.spec
