from sqlmodel import SQLModel, Session, create_engine

from models.users import User, UserSettings

database_file = "user_service.db"
database_connection_string = f"sqlite:///{database_file}"
connect_args = {"check_same_thread": False}

engine_url = create_engine(
    database_connection_string,
    echo=True,
    connect_args=connect_args,
)


def conn():
    SQLModel.metadata.create_all(engine_url)


def get_session():
    with Session(engine_url) as session:
        yield session