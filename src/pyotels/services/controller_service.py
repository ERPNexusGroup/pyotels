# src/services/controller_service.py
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from pyotels.config.settings import config
from pyotels.exceptions import NetworkError
from pyotels.utils.dates import date_to_day_id
from pyotels.utils.logger import get_logger


def build_room_index(categories_json: dict) -> dict[str, str]:
    """
    Devuelve un dict:
    {
        "102": "103",
        "103": "104",
        "Suite": "129",
        ...
    }
    """
    index = {}

    for category in categories_json.get("categories", []):
        for room in category.get("rooms", []):
            index[room["room_number"]] = room["room_id"]

    return index
def resolve_room_id(room_number: str, room_index: dict[str, str]) -> str:
    """
    Devuelve el room_id interno a partir del número visible
    """
    try:
        return room_index[str(room_number)]
    except KeyError:
        raise ValueError(f"Habitación '{room_number}' no existe en el catálogo")

class OtelsControllerService:
    """
    Capa de interacción UI con Playwright.
    Maneja clics, inputs, flujos y secuencias complejas.
    """

    def __init__(self, page: Page, categories_data: dict, ):
        self.page = page
        self.logger = get_logger(classname="OtelsControllerService")
        self.room_index = build_room_index(categories_data)

    # ================================================
    #              MANIPULACION DE CLICS             #
    # ================================================
    def click_button_by_text(self, text: str):
        selector = f"button:has-text('{text}')"
        self.click(selector)

    def click(self, selector: str, timeout: int = None):
        timeout = timeout or config.WAIT_FOR_SELECTOR

        try:
            self.logger.debug(f"Click en: {selector}")
            self.page.wait_for_selector(selector, state="visible", timeout=timeout)
            self.page.click(selector)
        except PlaywrightTimeoutError:
            raise NetworkError(f"No se pudo hacer click en {selector}")

    # ================================================
    #             MANIPULACION DE INPUTS             #
    # ================================================
    def fill_input(self, selector: str, value: str, clear: bool = True):
        try:
            self.logger.debug(f"Fill {selector} = {value}")
            self.page.wait_for_selector(selector, state="visible", timeout=config.WAIT_FOR_SELECTOR)
            if clear:
                self.page.fill(selector, "")
            self.page.fill(selector, value)
        except PlaywrightTimeoutError:
            raise NetworkError(f"No se pudo llenar el input {selector}")

    def set_date(self, selector: str, date_value: str):
        """
        date_value formato YYYY-MM-DD
        """
        self.fill_input(selector, date_value)
        self.page.keyboard.press("Enter")

    # ================================================
    #                 DRAG AND DROP                  #
    # ================================================
    def drag_and_select(self, start_selector: str, end_selector: str):
        try:
            start = self.page.wait_for_selector(start_selector)
            end = self.page.wait_for_selector(end_selector)

            start_box = start.bounding_box()
            end_box = end.bounding_box()

            self.page.mouse.move(
                start_box["x"] + 5,
                start_box["y"] + 5
            )
            self.page.mouse.down()

            self.page.mouse.move(
                end_box["x"] + 5,
                end_box["y"] + 5,
                steps=10
            )
            self.page.mouse.up()
        except Exception as e:
            raise NetworkError(f"Error en drag & select: {e}")

    # ================================================
    #                  FLUJOS CON UI                 #
    # ================================================
    def close_room_until(self, room_number: str, end_date: str):
        room_id = resolve_room_id(room_number, self.room_index)
        day_id_end = date_to_day_id(end_date)

        self.logger.info(
            f"Cerrando habitación {room_number} (room_id={room_id}) hasta {end_date}"
        )

        day_ids = self.page.evaluate("""
                                     ({roomId, dayIdEnd}) => {
                                         const cells = Array.from(
                                             document.querySelectorAll(
                                                 `td.calendar_td[room_id='${roomId}']`
                                             )
                                         ).sort((a, b) => Number(a.getAttribute('day_id')) - Number(b.getAttribute('day_id')));

                                         const result = [];
                                         let started = false;

                                         for (const td of cells) {
                                             const dayId = Number(td.getAttribute('day_id'));

                                             if (td.classList.contains('bg_padlock')) {
                                                 if (!started) continue;
                                                 break;
                                             }

                                             if (!started) started = true;
                                             if (dayId > dayIdEnd) break;

                                             result.push(dayId);
                                         }

                                         return result;
                                     }
                                     """, {
                                         "roomId": room_id,
                                         "dayIdEnd": day_id_end
                                     })

        if not day_ids:
            self.logger.warning("No hay días disponibles para cerrar")
            return

        self.page.evaluate("""
                           (dayIds) => {
                               dayIds.forEach(dayId => {
                                   const td = document.querySelector(`td[day_id='${dayId}']`);
                                   if (td) td.classList.add('ui-selected');
                               });
                           }
                           """, day_ids)


