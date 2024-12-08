from typing import List
from src.models.element import ElementResponse
from src.util.fpl_service import FplService

fpl_service = FplService()


def get_elements() -> List[any]:
    elements = fpl_service.fpl_data.get("elements")
    return elements


def get_element_by_id(id: int) -> ElementResponse:
    elements = get_elements()
    for element in elements:
        if element.get("id") == id:
            return ElementResponse(**element)

    return None


def get_elements_by_type(element_type: int) -> List[ElementResponse]:
    result = []
    for element in get_elements():
        if element.get("element_type") == element_type:
            result.append(ElementResponse(**element))

    return result


def get_element_types():
    element_types = fpl_service.fpl_data.get("element_types")
    return element_types
