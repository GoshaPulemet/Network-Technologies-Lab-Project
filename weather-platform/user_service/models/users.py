import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import EmailStr
from sqlmodel import SQLModel, Field


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True)
    password_hash: str
    name: str
    role: str = Field(default="user")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserSettings(SQLModel, table=True):
    __tablename__ = "user_settings"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", unique=True)
    temperature_unit: str = Field(default="C")
    language: str = Field(default="ru")
    default_city_id: Optional[uuid.UUID] = None


class NewUser(SQLModel):
    email: EmailStr
    password: str
    name: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "student@example.com",
                "password": "strong!!!",
                "name": "Student",
            }
        }
    }


class UserSignIn(SQLModel):
    email: EmailStr
    password: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "student@example.com",
                "password": "strong!!!",
            }
        }
    }


class UserPublic(SQLModel):
    """Пользователь БЕЗ пароля - это можно отдавать наружу."""
    id: uuid.UUID
    email: str
    name: str
    role: str


class UserSettingsUpdate(SQLModel):
    temperature_unit: Optional[str] = None
    language: Optional[str] = None
    default_city_id: Optional[uuid.UUID] = None

    model_config = {
        "json_schema_extra": {
            "example": {"temperature_unit": "F", "language": "en"}
        }
    }