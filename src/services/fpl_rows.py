"""FPL's live lists as response models."""

import logging
from typing import List, Type, TypeVar
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

Row = TypeVar("Row", bound=BaseModel)


def readable(rows: list, model: Type[Row], label: str, key: str) -> List[Row]:
    """Skips and logs rows that don't fit model. key names a row in the log."""
    found = []
    for row in rows:
        try:
            found.append(model.model_validate(row))
        except ValidationError as exc:
            row_id = row.get(key) if isinstance(row, dict) else None
            logger.warning("Skipping unreadable %s %r: %s", label, row_id, exc)
    return found
