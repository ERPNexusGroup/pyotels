"""Extraer funciones open_save/close_save del calendar."""
import re

with open("calendar_rendered.html", "r", encoding="utf-8", errors="replace") as f:
    html = f.read()

# Find open_save function definition
idx = html.find("function open_save")
if idx >= 0:
    print("=== open_save function ===")
    print(html[idx:idx+600])

idx = html.find("function close_save")
if idx >= 0:
    print("\n=== close_save function ===")
    print(html[idx:idx+600])

# Find what calls these functions
print("\n=== open_save callers ===")
callers = re.findall(r'open_save\([^)]{0,50}', html)
print(f"Callers: {callers[:5]}")

print("\n=== close_save callers ===")
callers = re.findall(r'close_save\([^)]{0,50}', html)
print(f"Callers: {callers[:5]}")

# Find the modal structure
print("\n=== Modal structure ===")
# Look for div with id containing save/modal
modal_divs = re.findall(r'<div[^>]*(?:id|class)="[^"]*(?:save|modal|popup)[^"]*"[^>]*>', html, re.I)
for m in modal_divs[:5]:
    print(f"  {m[:150]}")

# Find the actual onclick calls that trigger open_save
onclick_elems = re.findall(r'onclick="[^"]*open_save[^"]*"', html)
print(f"\nopen_save onclicks: {onclick_elems[:3]}")

onclick_elems = re.findall(r'onclick="[^"]*close_save[^"]*"', html)
print(f"close_save onclicks: {onclick_elems[:3]}")