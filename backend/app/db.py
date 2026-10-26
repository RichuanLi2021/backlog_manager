from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401  (register mappers before create_all)

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def _add_missing_columns():
    """Minimal additive migration so a local SQLite file survives model changes."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                default = column.default.arg if column.default is not None else None
                literal = _sql_literal(default)
                if column.name not in present:
                    clause = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {column.type}"
                    if literal is not None:
                        clause += f" DEFAULT {literal}"
                    conn.execute(text(clause))
                # Rows that existed before a column was added hold NULL there, which the
                # API cannot serialise as the str or int the model promises. Fill them.
                if literal is not None:
                    conn.execute(
                        text(f"UPDATE {table.name} SET {column.name} = {literal} "
                             f"WHERE {column.name} IS NULL")
                    )


def _sql_literal(value):
    """A model default as SQL, or None when it is not a plain constant."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None
