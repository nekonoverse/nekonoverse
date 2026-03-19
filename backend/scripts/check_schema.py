"""Post-migration schema sanity check.

Verifies that all tables defined in SQLAlchemy models actually exist in the
database.  Run after `alembic upgrade head` to catch inconsistencies caused
by partial restores or manual alembic_version edits.

Usage:
    python -m scripts.check_schema

Exit codes:
    0 — all tables present
    1 — missing tables detected
"""

import asyncio
import sys

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.models.base import Base

# Import all models via __init__ so Base.metadata is fully populated.
# New models added to app/models/__init__.py are automatically included.
import app.models  # noqa: F401


async def _get_db_tables() -> set[str]:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        db_tables = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
    await engine.dispose()
    return db_tables


def main() -> int:
    db_tables = asyncio.run(_get_db_tables())
    model_tables = set(Base.metadata.tables.keys())

    missing = model_tables - db_tables
    if missing:
        print(f"SCHEMA CHECK FAILED — missing tables: {', '.join(sorted(missing))}")
        return 1

    print(f"Schema OK — {len(model_tables)} tables verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
