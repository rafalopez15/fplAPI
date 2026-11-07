"""Path parameter types shared by the routers."""

from typing import Annotated
from fastapi import Path

# Postgres's integer maximum. A bigger id passes int validation, then fails the query
# with "integer out of range" (a 500), so ids are capped here and get a 422 instead.
POSTGRES_INT_MAX = 2_147_483_647


def _id_path(description: str):
    """A positive id Postgres can store. FPL ids are far below the cap (managers are
    around 10 million)."""
    return Path(gt=0, le=POSTGRES_INT_MAX, description=description)


# Written out as Annotated[int, ...] so type checkers see int. An alias built by a
# function call (fpl_id(...)) types the parameters as Any.
ElementId = Annotated[int, _id_path("The FPL player (element) id")]
ElementTypeId = Annotated[
    int, _id_path("The position: 1 goalkeeper, 2 defender, 3 midfielder, 4 forward")
]
EventId = Annotated[int, _id_path("The gameweek")]
ManagerId = Annotated[int, _id_path("The FPL manager (entry) id")]
