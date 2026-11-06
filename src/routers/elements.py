from typing import List
from fastapi import APIRouter, HTTPException
from src.models.element import ElementResponse
from src.routers.params import ElementId, ElementTypeId
from src.services import elements
from src.util.database import DataSession

elements_router = APIRouter()


@elements_router.get("/elements")
def get_elements(session: DataSession) -> List[ElementResponse]:
    """List every player."""
    return elements.get_elements(session)


@elements_router.get("/elements/{element_id}")
def get_elements_by_id(session: DataSession, element_id: ElementId) -> ElementResponse:
    """Get one player by FPL id. Returns 404 if no player has that id."""
    result = elements.get_element_by_id(session, element_id)
    if not result:
        raise HTTPException(status_code=404, detail="Element not found")

    return result


@elements_router.get("/elements/position/{element_type}")
def get_elements_by_type(
    session: DataSession, element_type: ElementTypeId
) -> List[ElementResponse]:
    """List the players in one position.

    element_type is 1 for goalkeepers, 2 for defenders, 3 for midfielders and 4
    for forwards. Returns 404 if no players match.
    """
    result = elements.get_elements_by_type(session, element_type)
    if not result:
        raise HTTPException(status_code=404, detail="Elements not found")

    return result
