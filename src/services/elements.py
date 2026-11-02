from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.db.models import Element
from src.models.element import ElementResponse


def get_elements(session: Session) -> List[ElementResponse]:
    """Return every player, in FPL id order. FPL calls players "elements"."""
    rows = session.scalars(select(Element).order_by(Element.id))
    return [ElementResponse.model_validate(row) for row in rows]


def get_element_by_id(session: Session, element_id: int) -> Optional[ElementResponse]:
    """Return the player with this FPL id, or None if there isn't one."""
    row = session.get(Element, element_id)
    return ElementResponse.model_validate(row) if row else None


def get_elements_by_type(session: Session, element_type: int) -> List[ElementResponse]:
    """Return the players in one position, or [] if none match.

    element_type is FPL's position id: 1 goalkeeper, 2 defender, 3 midfielder,
    4 forward.
    """
    rows = session.scalars(
        select(Element).where(Element.element_type == element_type).order_by(Element.id)
    )
    return [ElementResponse.model_validate(row) for row in rows]
