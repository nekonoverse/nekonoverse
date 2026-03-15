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

import sys

from sqlalchemy import create_engine, inspect

from app.config import settings
from app.models.base import Base

# Import all models so Base.metadata is populated
import app.models.actor  # noqa: F401
import app.models.bookmark  # noqa: F401
import app.models.custom_emoji  # noqa: F401
import app.models.delivery  # noqa: F401
import app.models.domain_block  # noqa: F401
import app.models.drive_file  # noqa: F401
import app.models.follow  # noqa: F401
import app.models.hashtag  # noqa: F401
import app.models.invitation_code  # noqa: F401
import app.models.moderation_log  # noqa: F401
import app.models.note  # noqa: F401
import app.models.note_attachment  # noqa: F401
import app.models.note_edit  # noqa: F401
import app.models.notification  # noqa: F401
import app.models.oauth  # noqa: F401
import app.models.passkey  # noqa: F401
import app.models.pinned_note  # noqa: F401
import app.models.poll_vote  # noqa: F401
import app.models.push_subscription  # noqa: F401
import app.models.reaction  # noqa: F401
import app.models.report  # noqa: F401
import app.models.server_setting  # noqa: F401
import app.models.user  # noqa: F401
import app.models.user_block  # noqa: F401
import app.models.user_mute  # noqa: F401


def main() -> int:
    url = settings.database_url.replace("+asyncpg", "")
    engine = create_engine(url)
    inspector = inspect(engine)
    db_tables = set(inspector.get_table_names())
    model_tables = set(Base.metadata.tables.keys())

    missing = model_tables - db_tables
    if missing:
        print(f"SCHEMA CHECK FAILED — missing tables: {', '.join(sorted(missing))}")
        return 1

    print(f"Schema OK — {len(model_tables)} tables verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
