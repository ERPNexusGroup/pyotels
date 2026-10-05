"""Test: availability por categoría publicada en el markup del calendario.

OtelMS no tiene un endpoint de availability; el calendario HTTP trae, en la fila
de resumen de cada categoría (`<td room_id="0">`), un `div.calendar_sum` con el
número de habitaciones disponibles para ese día:

    <td category_id="13" class="calendar_td" day_id="20731" room_id="0">
      <div class="calendar_sum" id="availability_13_20731" style="width: 35px;">8</div>

Este script contrasta ese número contra `habitaciones - ocupadas` calculadas a
mano para comprobar si el dato es redundante o si el portal lo restringe.
"""

import asyncio
from collections import defaultdict

from bs4 import BeautifulSoup

from otelms.config.settings import get_settings
from otelms.scraping.calendar_markup_v2 import (
    TABLE_CLASS,
    parse_categories_v2,
    day_id_to_date_table,
)
from otelms.scraping.http_calendar import fetch_calendar_html


async def main() -> None:
    settings = get_settings()
    html = await fetch_calendar_html(
        hotel_id="18330",
        username=settings.otelms_default_username,
        password=settings.otelms_default_password,
    )
    _report(html)


def _report(html: str) -> None:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_=TABLE_CLASS)

    availability: dict[tuple[str, str], int] = {}
    for td in table.find_all("td", attrs={"room_id": "0"}):
        cat_id, day_id = td.get("category_id"), td.get("day_id")
        div = td.find("div", class_="calendar_sum")
        if not (cat_id and day_id and div is not None):
            continue
        raw = div.get_text(strip=True)
        if raw.lstrip("-").isdigit():
            availability[(str(cat_id), day_id_to_date_table(str(day_id)))] = int(raw)

    categories = parse_categories_v2(html)
    rooms_by_cat = {c["id"]: len(c["rooms"]) for c in categories}
    room_cat = {r["id"]: c["id"] for c in categories for r in c["rooms"]}

    occupied: set[tuple[str, str]] = set()
    for td in table.find_all("td", class_="calendar_td"):
        room_id, day_id = td.get("room_id"), td.get("day_id")
        if not room_id or room_id == "0" or not day_id:
            continue
        if td.find("div", class_="calendar_item") is None:
            continue
        occupied.add((str(room_id), day_id_to_date_table(str(day_id))))

    per_cat_day: dict[tuple[str, str], set[str]] = defaultdict(set)
    for room_id, date in occupied:
        cat_id = room_cat.get(room_id)
        if cat_id:
            per_cat_day[(cat_id, date)].add(room_id)

    print(f"Categorías: {len(rooms_by_cat)} | celdas availability: {len(availability)}")
    if availability:
        dates = sorted({d for _, d in availability})
        print(f"Rango: {dates[0]} .. {dates[-1]} ({len(dates)} días)\n")

    print(f"{'cat':>4} {'rooms':>5} | {'fecha':<11} | {'OtelMS':>7} | {'calc':>4} | diff")
    diff = same = 0
    for (cat_id, date), value in sorted(
        availability.items(), key=lambda kv: (kv[0][0], kv[0][1])
    ):
        calc = rooms_by_cat.get(cat_id, 0) - len(per_cat_day.get((cat_id, date), ()))
        if calc != value:
            diff += 1
        else:
            same += 1
        if diff <= 15 or calc == value:
            flag = "" if calc == value else "  <-- DIFIERE"
            print(
                f"{cat_id:>4} {rooms_by_cat.get(cat_id, 0):>5} | {date:<11}"
                f" | {value:>7} | {calc:>4}{flag}"
            )

    print(f"\ncoinciden: {same} | difieren: {diff}")
    print("Si difieren, el número del portal manda: no se puede recalcular por diferencias.")


asyncio.run(main())

soup = BeautifulSoup(html, "lxml")
table = soup.find("table", class_=TABLE_CLASS)

availability: dict[tuple[str, str], int] = {}
for td in table.find_all("td", attrs={"room_id": "0"}):
    cat_id, day_id = td.get("category_id"), td.get("day_id")
    div = td.find("div", class_="calendar_sum")
    if not (cat_id and day_id and div is not None):
        continue
    raw = div.get_text(strip=True)
    if raw.lstrip("-").isdigit():
        availability[(str(cat_id), day_id_to_date_table(str(day_id)))] = int(raw)

categories = parse_categories_v2(html)
rooms_by_cat = {c["id"]: len(c["rooms"]) for c in categories}
room_cat = {r["id"]: c["id"] for c in categories for r in c["rooms"]}

occupied: dict[tuple[str, str], set[str]] = defaultdict(set)
for td in table.find_all("td", class_="calendar_td"):
    room_id, day_id = td.get("room_id"), td.get("day_id")
    if not room_id or room_id == "0" or not day_id:
        continue
    if td.find("div", class_="calendar_item") is None:
        continue
    occupied[(str(room_id), day_id_to_date_table(str(day_id)))].add(str(room_id))

per_cat_day: dict[tuple[str, str], set[str]] = defaultdict(set)
for (room_id, date), _ in occupied.items():
    cat_id = room_cat.get(room_id)
    if cat_id:
        per_cat_day[(cat_id, date)].add(room_id)

print(f"Categorías: {len(rooms_by_cat)} | celdas availability: {len(availability)}")
if availability:
    dates = sorted({d for _, d in availability})
    print(f"Rango: {dates[0]} .. {dates[-1]} ({len(dates)} días)\n")

print(f"{'cat':>4} {'rooms':>5} | {'fecha':<11} | {'OtelMS':>7} | {'calc':>4} | diff")
diff = same = 0
for (cat_id, date), value in sorted(availability.items(), key=lambda kv: (kv[0][0], kv[0][1])):
    calc = rooms_by_cat.get(cat_id, 0) - len(per_cat_day.get((cat_id, date), ()))
    if calc != value:
        diff += 1
    else:
        same += 1
    if diff <= 15 or calc == value:
        flag = "" if calc == value else "  <-- DIFIERE"
        print(f"{cat_id:>4} {rooms_by_cat.get(cat_id, 0):>5} | {date:<11} | {value:>7} | {calc:>4}{flag}")

print(f"\ncoinciden: {same} | difieren: {diff}")
print("Si difieren, el número del portal manda: no se puede recalcular por diferencias.")