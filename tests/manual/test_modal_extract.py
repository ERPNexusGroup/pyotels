"""Extraer URLs y estructura del ModalReservationCalendar + availability_arr."""
import re
import json

with open("calendar_rendered.html", "r", encoding="utf-8", errors="replace") as f:
    html = f.read()

# Find the modal content
modal_match = re.search(r'<div[^>]*id="ModalReservationCalendar".*?</div>\s*</div>\s*</div>\s*</div>', html, re.DOTALL)
if modal_match:
    modal_html = modal_match.group()
    print(f"Modal HTML: {len(modal_html)} chars")
else:
    print("Modal not found - searching for availability patterns")

# Find availability_arr references
avail_refs = re.findall(r'availability_arr[^;]{0,200}', html, re.DOTALL)
print(f"\navailability_arr refs: {len(avail_refs)}")
for ref in avail_refs[:3]:
    print(f"  {ref[:150]}")

# Find $url definitions
url_defs = re.findall(r'\$url\s*=\s*[^;]{0,100}', html)
print(f"\n$url definitions: {url_defs[:5]}")

# Find close_save/open_save function bodies
for func_name in ["open_save", "close_save"]:
    idx = html.find(f"function {func_name}")
    if idx >= 0:
        end = html.find("}", idx + 50)
        # Find the end of function (account for nested braces)
        brace_count = 0
        for i in range(idx + len(func_name) + 12, len(html)):
            if html[i] == "{":
                brace_count += 1
            elif html[i] == "}":
                brace_count -= 1
                if brace_count == 0:
                    end = i + 1
                    break
        func_body = html[idx:end]
        print(f"\n=== {func_name} ===")
        print(func_body[:400])

# Find room_id in modal
room_ids = re.findall(r'room_id[^\n]{0,100}', html)
print(f"\nroom_id refs: {len(room_ids)}")
for r in room_ids[:3]:
    print(f"  {r[:100]}")

# Find AJAX URLs
ajax_urls = re.findall(r"['\"](/reservation_c2/[^\"]+)['\"]", html)
ajax_urls = [u for u in set(ajax_urls) if any(kw in u.lower() for kw in ['block', 'save', 'avail', 'room', 'status', 'calendar'])]
print(f"\nReservation AJAX URLs: {ajax_urls[:10]}")

# Find date inputs
date_inputs = re.findall(r'<input[^>]*(?:datein|dateout|start_date|end_date)[^>]*>', html, re.I)
print(f"\nDate inputs: {len(date_inputs)}")

# Find room select
room_select = re.findall(r'<select[^>]*(?:room|roomname)[^>]*>', html, re.I)
print(f"Room selects: {len(room_select)}")