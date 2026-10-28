#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests -v
python3 tools/embed.py
mkdir -p .local
c++ -std=c++17 -Itests/fakes -Ifirmware/include tests/firmware_test.cpp -o .local/firmware-tests
.local/firmware-tests
python3 - <<'PY'
from pathlib import Path
import re
s=Path('web/index.html').read_text()
Path('.local/dashboard.js').write_text(re.search(r'<script>(.*?)</script>',s,re.S).group(1))
PY
node --check .local/dashboard.js
git diff --check
