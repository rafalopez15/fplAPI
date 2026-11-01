from typing import List, Optional
from src.models.element import ElementResponse
from src.util.fpl_service import FplService

fpl_service = FplService()


def get_elements() -> List[dict]:
    """Return every player as the raw dicts FPL sends. FPL calls players "elements"."""
    elements = fpl_service.get_data("elements")
    return elements


def get_element_by_id(element_id: int) -> Optional[ElementResponse]:
    """Return the player with this FPL id, or None if there isn't one."""
    elements = get_elements()
    for element in elements:
        if element.get("id") == element_id:
            return ElementResponse(**element)

    return None


def get_elements_by_type(element_type: int) -> List[ElementResponse]:
    """Return the players in one position, or [] if none match.

    element_type is FPL's position id: 1 goalkeeper, 2 defender, 3 midfielder,
    4 forward.
    """
    result = []
    for element in get_elements():
        if element.get("element_type") == element_type:
            result.append(ElementResponse(**element))

    return result


def get_element_types():
    """Return FPL's positions, which map each element_type id to a name like "Midfielder"."""
    element_types = fpl_service.get_data("element_types")
    return element_types
