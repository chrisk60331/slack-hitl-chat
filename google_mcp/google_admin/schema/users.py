from pydantic import BaseModel


class User(BaseModel):
    id: str
    name: str
    email: str
    role: str
    status: str
    created_at: str
    updated_at: str
