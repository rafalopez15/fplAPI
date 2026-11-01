from typing import List
from fastapi import APIRouter, HTTPException
from src.models.element import ElementResponse
from src.services import elements

elements_router = APIRouter()


@elements_router.get("/elements")
async def get_elements():
    """List every player with all the fields FPL provides."""
    return elements.get_elements()


@elements_router.get("/elements/{element_id}")
async def get_elements_by_id(element_id: int) -> ElementResponse:
    """Get one player by FPL id. Returns 404 if no player has that id."""
    result = elements.get_element_by_id(element_id)
    if not result:
        raise HTTPException(status_code=404, detail="Element not found")

    return result


@elements_router.get("/elements/position/{element_type}")
async def get_elements_by_type(element_type: int) -> List[ElementResponse]:
    """List the players in one position.

    element_type is 1 for goalkeepers, 2 for defenders, 3 for midfielders and 4
    for forwards. Returns 404 if no players match.
    """
    result = elements.get_elements_by_type(element_type)
    if not result:
        raise HTTPException(status_code=404, detail="Elements not found")

    return result
