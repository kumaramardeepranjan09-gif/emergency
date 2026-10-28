"""Embed the offline dashboard before each PlatformIO build."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
html = (root / 'web/index.html').read_text()
assert ')DASHBOARD"' not in html
(root / 'firmware/include/dashboard.h').write_text(
    '#pragma once\nconst char PAGE[] PROGMEM = R"DASHBOARD(' + html + ')DASHBOARD";\n')
