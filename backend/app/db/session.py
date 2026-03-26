from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base

_engine = None


def _resolved_database_url(raw_url: str) -> str:
    """
    Normalize sqlite URLs so relative file paths are anchored to backend root.

    This avoids startup failures when process cwd differs (e.g. launched outside backend/).
    """
    url = make_url(raw_url)
    if url.drivername != "sqlite":
        return raw_url
    db_name = url.database
    if not db_name or db_name == ":memory:":
        return raw_url

    db_path = Path(db_name).expanduser()
    if not db_path.is_absolute():
        backend_root = Path(__file__).resolve().parents[2]
        db_path = backend_root / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = _resolved_database_url(settings.database_url)
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(url, connect_args=connect_args)
    return _engine


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def init_db() -> None:
    """Create tables if they do not exist (minimal v1; use Alembic for migrations later)."""
    import app.db.models  # noqa: F401 — register models on Base.metadata

    Base.metadata.create_all(bind=get_engine())


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
