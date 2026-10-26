import hashlib
import hmac
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from database.connections import get_session
from models.users import (NewUser, User, UserPublic, UserSettings, UserSettingsUpdate, UserSignIn)

user_router = APIRouter(
    tags=["User"]
)

ITERATIONS = 100_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split("$")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), ITERATIONS)
    return hmac.compare_digest(digest.hex(), digest_hex)


@user_router.post("/signup")
def sign_new_user(data: NewUser, session: Session = Depends(get_session)) -> dict:
    exists = session.exec(select(User).where(User.email == data.email)).first()
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with supplied email exists"
        )
    user = User(email=data.email,
                password_hash=hash_password(data.password),
                name=data.name)
    session.add(user)
    session.add(UserSettings(user_id=user.id))
    session.commit()
    return {
        "message": "User successfully registered!",
        "user_id": str(user.id)
    }


@user_router.post("/signin")
def sign_user_in(data: UserSignIn, session: Session = Depends(get_session)) -> dict:
    user = session.exec(select(User).where(User.email == data.email)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User does not exist"
        )
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Wrong credentials passed"
        )
    return {
        "message": "User signed in successfully",
        "user_id": str(user.id)
    }


@user_router.get("/settings/{user_id}", response_model=UserSettings)
def retrieve_settings(user_id: uuid.UUID,
                      session: Session = Depends(get_session)) -> UserSettings:
    settings = session.exec(
        select(UserSettings).where(UserSettings.user_id == user_id)
    ).first()
    if settings:
        return settings
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Settings for supplied user do not exist"
    )


@user_router.put("/settings/{user_id}", response_model=UserSettings)
def update_settings(user_id: uuid.UUID, new_data: UserSettingsUpdate,
                    session: Session = Depends(get_session)) -> UserSettings:
    settings = session.exec(
        select(UserSettings).where(UserSettings.user_id == user_id)
    ).first()
    if not settings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Settings for supplied user do not exist"
        )
    for key, value in new_data.model_dump(exclude_unset=True).items():
        setattr(settings, key, value)
    session.add(settings)
    session.commit()
    session.refresh(settings)
    return settings


@user_router.get("/{user_id}", response_model=UserPublic)
def retrieve_user(user_id: uuid.UUID, session: Session = Depends(get_session)) -> User:
    user = session.get(User, user_id)
    if user:
        return user
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="User with supplied ID does not exist"
    )