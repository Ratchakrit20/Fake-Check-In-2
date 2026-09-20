from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ..core.config import get_settings
from .models import Base

settings = get_settings()
is_sqlite = settings.database.url.startswith("sqlite")
engine = create_async_engine(
    settings.database.url,
    pool_pre_ping=True,
    connect_args={"timeout": 60} if is_sqlite else {},
)


if is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def init_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        if is_sqlite:
            columns = {
                row[1]
                for row in (await connection.execute(text("PRAGMA table_info(analysis_jobs)"))).all()
            }
            additions = {
                "started_at": "DATETIME",
                "completed_at": "DATETIME",
                "duration_seconds": "FLOAT",
            }
            for column, data_type in additions.items():
                if column not in columns:
                    await connection.execute(text(f"ALTER TABLE analysis_jobs ADD COLUMN {column} {data_type}"))
        else:
            await connection.execute(text("ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS started_at TIMESTAMP"))
            await connection.execute(text("ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP"))
            await connection.execute(text("ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS duration_seconds DOUBLE PRECISION"))
        await connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_pair_level_score ON pairwise_results (relationship_level, relationship_score)")
        )


async def get_session():
    async with SessionFactory() as session:
        yield session
