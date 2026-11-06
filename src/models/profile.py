from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class ProfileResponse(BaseModel):
    """The signed-in user's account, built from a profiles row."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID  # the Supabase Auth user id
    created_at: datetime
