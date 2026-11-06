"""Path parameter types shared by the routers."""
from typing import Annotated
from fastapi import Path

# Postgres's integer maximum. A bigger id passes int validation, then fails the query
# with "integer out of range" (a 500), so ids are capped here and get a 422 instead.
POSTGRES_INT_MAX = 2_147_483_647


def fpl_id(description: str):
    """An id path parameter: a positive integer Postgres can store. FPL ids are far
    below the cap (managers are around 10 million)."""
    return Annotated[int, Path(gt=0, le=POSTGRES_INT_MAX, description=description)]


ElementId = fpl_id("The FPL player (element) id")
ElementTypeId = fpl_id("The position: 1 goalkeeper, 2 defender, 3 midfielder, 4 forward")
EventId = fpl_id("The gameweek")
ManagerId = fpl_id("The FPL manager (entry) id")
