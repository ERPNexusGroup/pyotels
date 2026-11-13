"""Patch: reordenar sync loop para extraer rooms before upsert_reservation."""
from pathlib import Path

# El objetivo se resuelve contra la raiz del repo, no contra el CWD: asi el
# script no reescribe el calendar_sync_service.py de otro checkout.
TARGET = Path(__file__).resolve().parents[2] / "src/otelms/services/calendar_sync_service.py"

content = TARGET.read_text(encoding="utf-8")

old_block = """            try:
                # 1. Upsert reservation
                self._upsert_reservation(res)
                stats[\"reservations\"] += 1

                # 2. Folio → guests + services + payments + rooms
                fol_resp = self.session.get(
                    f\"https://desktop.otelms.com/reservation_c2/folio/{res['resid']}\",
                    timeout=20,
                )
                if fol_resp.status_code == 200:
                    folio = parse_folio(fol_resp.text, str(res[\"resid\"]))

                    # Extract + persist room_type + room_number
                    room_type = extract_room_type(fol_resp.text)
                    room_number = extract_room_number(fol_resp.text)
                    if room_type or room_number:
                        self._upsert_room(room_type, room_number, fol_resp.text)
                        # Update reservation's room_id if room_number found
                        if room_number:
                            res[\"room_number\"] = room_number"""

new_block = """            try:
                # 1. Folio → extract room_type + room_number + guest + services
                fol_resp = self.session.get(
                    f\"https://desktop.otelms.com/reservation_c2/folio/{res['resid']}\",
                    timeout=20,
                )
                if fol_resp.status_code == 200:
                    folio = parse_folio(fol_resp.text, str(res[\"resid\"]))

                    # Extract + persist room_type + room_number (before upsert_reservation)
                    room_type = extract_room_type(fol_resp.text)
                    room_number = extract_room_number(fol_resp.text)
                    if room_type or room_number:
                        self._upsert_room(room_type, room_number, fol_resp.text)
                        if room_number:
                            res[\"room_number\"] = room_number"""

if old_block in content:
    TARGET.write_text(content.replace(old_block, new_block), encoding="utf-8")
    print("Reordered: rooms before reservation")
else:
    print("Old block not found")