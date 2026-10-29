from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ..core.config import get_settings
from ..services.source_filename import parse_job_type, parse_source_reference
from .models import Base, ImageRecord

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
            image_columns = {
                row[1]
                for row in (await connection.execute(text("PRAGMA table_info(images)"))).all()
            }
            image_additions = {
                "source_technician_id": "VARCHAR(10)",
                "source_job_number": "VARCHAR(10)",
                "source_checkin_date": "VARCHAR(8)",
                "source_job_type": "VARCHAR(20)",
                "source_captured_at": "VARCHAR(32)",
                "ai_metadata_json": "TEXT",
                "image_quality_status": "VARCHAR(30)",
                "image_quality_reason": "VARCHAR(80)",
                "near_black_ratio": "FLOAT",
            }
            for column, data_type in image_additions.items():
                if column not in image_columns:
                    await connection.execute(text(f"ALTER TABLE images ADD COLUMN {column} {data_type}"))
            job_columns = {
                row[1]
                for row in (await connection.execute(text("PRAGMA table_info(analysis_jobs)"))).all()
            }
            job_additions = {
                "started_at": "DATETIME",
                "completed_at": "DATETIME",
                "duration_seconds": "FLOAT",
            }
            for column, data_type in job_additions.items():
                if column not in job_columns:
                    await connection.execute(text(f"ALTER TABLE analysis_jobs ADD COLUMN {column} {data_type}"))
            export_image_columns = {
                row[1]
                for row in (await connection.execute(text("PRAGMA table_info(export_report_images)"))).all()
            }
            if "source_technician_id" not in export_image_columns:
                await connection.execute(text("ALTER TABLE export_report_images ADD COLUMN source_technician_id VARCHAR(10)"))
            report_columns = {
                row[1]
                for row in (await connection.execute(text("PRAGMA table_info(export_reports)"))).all()
            }
            if "summary_xlsx_path" not in report_columns:
                await connection.execute(text("ALTER TABLE export_reports ADD COLUMN summary_xlsx_path TEXT"))
        else:
            await connection.execute(text("ALTER TABLE images ADD COLUMN IF NOT EXISTS source_job_number VARCHAR(10)"))
            await connection.execute(text("ALTER TABLE images ADD COLUMN IF NOT EXISTS source_checkin_date VARCHAR(8)"))
            await connection.execute(text("ALTER TABLE images ADD COLUMN IF NOT EXISTS source_technician_id VARCHAR(10)"))
            await connection.execute(text("ALTER TABLE images ADD COLUMN IF NOT EXISTS source_job_type VARCHAR(20)"))
            await connection.execute(text("ALTER TABLE images ADD COLUMN IF NOT EXISTS source_captured_at VARCHAR(32)"))
            await connection.execute(text("ALTER TABLE images ADD COLUMN IF NOT EXISTS ai_metadata_json TEXT"))
            await connection.execute(text("ALTER TABLE images ADD COLUMN IF NOT EXISTS image_quality_status VARCHAR(30)"))
            await connection.execute(text("ALTER TABLE images ADD COLUMN IF NOT EXISTS image_quality_reason VARCHAR(80)"))
            await connection.execute(text("ALTER TABLE images ADD COLUMN IF NOT EXISTS near_black_ratio DOUBLE PRECISION"))
            await connection.execute(text("ALTER TABLE export_report_images ADD COLUMN IF NOT EXISTS source_technician_id VARCHAR(10)"))
            await connection.execute(text("ALTER TABLE export_reports ADD COLUMN IF NOT EXISTS summary_xlsx_path TEXT"))
            await connection.execute(text("ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS started_at TIMESTAMP"))
            await connection.execute(text("ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP"))
            await connection.execute(text("ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS duration_seconds DOUBLE PRECISION"))
        await connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_pair_level_score ON pairwise_results (relationship_level, relationship_score)")
        )
        await connection.execute(text("CREATE INDEX IF NOT EXISTS ix_images_image_quality_status ON images (image_quality_status)"))
        await connection.execute(text("CREATE INDEX IF NOT EXISTS ix_images_source_job_number ON images (source_job_number)"))
        await connection.execute(text("CREATE INDEX IF NOT EXISTS ix_images_source_checkin_date ON images (source_checkin_date)"))
        await connection.execute(text("CREATE INDEX IF NOT EXISTS ix_images_source_technician_id ON images (source_technician_id)"))
        await connection.execute(text("CREATE INDEX IF NOT EXISTS ix_images_source_job_type ON images (source_job_type)"))

    # Backfill existing libraries created before source metadata was persisted.
    async with SessionFactory() as session:
        records = list(await session.scalars(select(ImageRecord).where(
            ImageRecord.source_job_number.is_(None)
            | ImageRecord.source_technician_id.is_(None)
            | (ImageRecord.source_job_type.is_(None) & ImageRecord.source_checkin_date.is_not(None))
        )))
        for record in records:
            reference = parse_source_reference(record.original_filename)
            if reference is not None:
                record.source_job_number = reference.job_number
                record.source_checkin_date = reference.checkin_date
                record.source_technician_id = reference.technician_id
                record.source_job_type = reference.job_type
            elif record.source_job_type is None:
                record.source_job_type = parse_job_type(record.original_filename)
        await session.commit()


async def get_session():
    async with SessionFactory() as session:
        yield session
