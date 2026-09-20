from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def new_id() -> str:
    return str(uuid.uuid4())


class ImageRecord(Base):
    __tablename__ = "images"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    phash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    analysis_status: Mapped[str] = mapped_column(String(30), default="QUEUED")


class ImageEmbedding(Base):
    __tablename__ = "image_embeddings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    image_id: Mapped[str] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), index=True)
    embedding: Mapped[bytes] = mapped_column(LargeBinary)
    model_name: Mapped[str] = mapped_column(String(100))
    model_version: Mapped[str] = mapped_column(String(150))
    configuration_version: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("image_id", "model_name", "model_version"),)


class PairwiseResult(Base):
    __tablename__ = "pairwise_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    image_a_id: Mapped[str] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"))
    image_b_id: Mapped[str] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"))
    phash_distance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dino_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    sift_matches: Mapped[int] = mapped_column(Integer, default=0)
    ransac_inliers: Mapped[int] = mapped_column(Integer, default=0)
    ransac_inlier_ratio: Mapped[float] = mapped_column(Float, default=0)
    flip_detected: Mapped[int] = mapped_column(Integer, default=0)
    relationship_score: Mapped[float] = mapped_column(Float)
    relationship_level: Mapped[str] = mapped_column(String(40))
    details_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("image_a_id", "image_b_id", name="uq_pair"),
        Index("ix_pair_score", "relationship_score"),
        Index("ix_pair_level_score", "relationship_level", "relationship_score"),
    )


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)


class AnalysisJobItem(Base):
    __tablename__ = "analysis_job_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    image_id: Mapped[str] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED")
    __table_args__ = (UniqueConstraint("job_id", "position", name="uq_job_position"),)
