from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON as SQLJSON, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


JSON = SQLJSON().with_variant(JSONB, "postgresql")


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    hostname: Mapped[str] = mapped_column(String(255))
    os: Mapped[str] = mapped_column(String(255))
    agent_version: Mapped[str] = mapped_column(String(64))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    measurements: Mapped[list["Measurement"]] = relationship(back_populates="agent")


class Measurement(Base):
    __tablename__ = "measurements"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    network: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    target_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    collector_status: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    agent: Mapped[Agent] = relationship(back_populates="measurements")
    rule_diagnosis: Mapped["RuleDiagnosis | None"] = relationship(back_populates="measurement", uselist=False)
    ai_diagnosis: Mapped["AIDiagnosis | None"] = relationship(back_populates="measurement", uselist=False)


class RuleDiagnosis(Base):
    __tablename__ = "rule_diagnoses"
    id: Mapped[int] = mapped_column(primary_key=True)
    measurement_id: Mapped[int] = mapped_column(ForeignKey("measurements.id"), unique=True)
    severity: Mapped[str] = mapped_column(String(16))
    findings: Mapped[list] = mapped_column(JSON, default=list)
    triggered_rules: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    measurement: Mapped[Measurement] = relationship(back_populates="rule_diagnosis")


class AIDiagnosis(Base):
    __tablename__ = "ai_diagnoses"
    id: Mapped[int] = mapped_column(primary_key=True)
    measurement_id: Mapped[int] = mapped_column(ForeignKey("measurements.id"), unique=True)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    primary_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    measured_facts: Mapped[list] = mapped_column(JSON, default=list)
    rule_findings: Mapped[list] = mapped_column(JSON, default=list)
    hypotheses: Mapped[list] = mapped_column(JSON, default=list)
    impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendations: Mapped[list] = mapped_column(JSON, default=list)
    additional_checks: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    measurement: Mapped[Measurement] = relationship(back_populates="ai_diagnosis")
