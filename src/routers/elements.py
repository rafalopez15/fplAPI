from typing import List
from fastapi import APIRouter, HTTPException
from src.models.element import ElementResponse
from src.services import elements

elements_router = APIRouter()


@elements_router.get("/elements")
async def get_elements():
    result = elements.get_elements()
    if not result:
        raise HTTPException(status_code=400, detail="Not able to retrieve elements")

    return result


@elements_router.get("/elements/{element_id}")
async def get_elements_by_id(element_id: int) -> ElementResponse:
    result = elements.get_element_by_id(element_id)
    if not result:
        raise HTTPException(status_code=404, detail="Element not found")

    return result


@elements_router.get("/elements/position/{element_type}")
async def get_elements_by_type(element_type: int) -> List[ElementResponse]:
    result = elements.get_elements_by_type(element_type)
    if not result:
        raise HTTPException(status_code=404, detail="Elements not found")

    return result
