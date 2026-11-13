"""Test room number patterns on rendered folio."""
import re

with open("folio_23419_rendered.html", "r", encoding="utf-8", errors="replace") as f:
    html = f.read()

patterns = [
    r"Habitaci[oó]n[:\s]*<b[^>]*>[^<]*</b><br>\s*(\d+)",
    r"Habitaci[oó]n[^0-9]*(\d+)",
]
for p in patterns:
    m = re.search(p, html, re.I)
    if m:
        print(f"Pattern: MATCHED {m.group(1)}")
    else:
        print("Pattern: NO MATCH")