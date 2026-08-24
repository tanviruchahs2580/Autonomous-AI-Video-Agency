from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import APP_ROOT, get_settings

MIGRATIONS_DIR = APP_ROOT / "agency" / "migrations"

_engine = None
_session_factory: sessionmaker | None = None


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite:///"):
        raw = url[len("sqlite:///") :]
        if raw and raw != ":memory:":
            Path(raw).parent.mkdir(parents=True, exist_ok=True)


def get_engine():
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _ensure_sqlite_dir(settings.db_url)
        connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}
        _engine = create_engine(settings.db_url, connect_args=connect_args, pool_pre_ping=True)
        _session_factory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    if _session_factory is None:
        raise RuntimeError("database session factory not initialized")
    session: Session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def applied_versions(db: Session) -> list[str]:
    db.execute(
        text("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    )
    db.commit()
    rows = db.execute(text("SELECT version FROM schema_migrations ORDER BY version")).fetchall()
    return [r[0] for r in rows]


def available_migrations() -> list[Path]:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return [f for f in files if f.stem != "schema"]


def run_migrations(db: Session) -> list[str]:
    done = applied_versions(db)
    executed: list[str] = []
    for path in available_migrations():
        version = path.stem
        if version in done:
            continue
        sql_text = path.read_text(encoding="utf-8")
        statements = [s.strip() for s in sql_text.split(";") if s.strip()]
        for stmt in statements:
            db.execute(text(stmt))
        db.execute(text("INSERT INTO schema_migrations (version) VALUES (:v)"), {"v": version})
        db.commit()
        executed.append(version)
    return executed


def init_db() -> list[str]:
    with session_scope() as db:
        return run_migrations(db)


def fresh_test_db(tmp_path: Path) -> str:
    reset_engine()
    return f"sqlite:///{(tmp_path / 'test.db').as_posix()}"


def backup_database(target: Path) -> Path:
    settings = get_settings()
    target.parent.mkdir(parents=True, exist_ok=True)
    if settings.db_url.startswith("sqlite"):
        src = settings.db_url.replace("sqlite:///", "")
        shutil.copyfile(src, target)
        return target
    engine = get_engine()
    if engine.dialect.name == "postgresql":
        raise RuntimeError("PostgreSQL backup requires pg_dump; use infrastructure-level backups")
    raise RuntimeError(f"Unsupported dialect {engine.dialect.name}")
