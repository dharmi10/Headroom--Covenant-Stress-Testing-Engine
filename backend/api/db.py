"""Storage: deals, agreements, versioned formulas, mappings and runs.

SQLite through SQLAlchemy, one file. Headroom has one user and needs no
concurrency; what it does need is that an approved formula version and a stored
run are never silently rewritten, which is enforced here by storing each
version as its own immutable row.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

DEFAULT_URL = "sqlite:///headroom.db"


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Deal(Base):
    """One borrower and one credit agreement."""

    __tablename__ = "deals"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    borrower: Mapped[str] = mapped_column(String(200))
    cik: Mapped[str] = mapped_column(String(10))
    exhibit_url: Mapped[str] = mapped_column(Text)
    source_hash: Mapped[str] = mapped_column(String(80))
    entity_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    agreement_text: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    versions: Mapped[list["FormulaRow"]] = relationship(
        back_populates="deal", cascade="all, delete-orphan", order_by="FormulaRow.version"
    )
    mappings: Mapped[list["MappingRow"]] = relationship(
        back_populates="deal", cascade="all, delete-orphan"
    )
    runs: Mapped[list["RunRow"]] = relationship(
        back_populates="deal", cascade="all, delete-orphan"
    )


class FormulaRow(Base):
    """One formula version. Approved rows are never updated again."""

    __tablename__ = "formula_versions"
    __table_args__ = (UniqueConstraint("deal_id", "version", name="uq_deal_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    source_hash: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    compile_log: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    deal: Mapped[Deal] = relationship(back_populates="versions")


class MappingRow(Base):
    """The current mapping record for one item of one deal."""

    __tablename__ = "mappings"
    __table_args__ = (UniqueConstraint("deal_id", "formula_item", name="uq_deal_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id"))
    formula_item: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    deal: Mapped[Deal] = relationship(back_populates="mappings")


class RunRow(Base):
    """One stored run, with the versions it was built from."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id"))
    test_date: Mapped[str] = mapped_column(String(10))
    formula_version: Mapped[int] = mapped_column(Integer)
    evaluator_version: Mapped[str] = mapped_column(String(60))
    output_hash: Mapped[str] = mapped_column(String(80))
    superseded: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    deal: Mapped[Deal] = relationship(back_populates="runs")


def make_engine(url: str = DEFAULT_URL, *, echo: bool = False):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, echo=echo, future=True, connect_args=connect_args)
    Base.metadata.create_all(engine)
    return engine


def make_session_factory(url: str = DEFAULT_URL):
    return sessionmaker(bind=make_engine(url), expire_on_commit=False, future=True)
