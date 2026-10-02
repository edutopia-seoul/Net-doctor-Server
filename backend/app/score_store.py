from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import HealthScore, Measurement
from .schemas import HealthScoreOut
from .scoring import ScoreConfig, calculate_score, config_hash


def validate_stored_policy(db: Session, config: ScoreConfig):
    hashes = db.scalars(select(HealthScore.config_hash).where(HealthScore.score_version == config.score_version).distinct()).all()
    if any(value != config_hash(config) for value in hashes):
        raise ValueError("score config changed: use a new score_version; stored results cannot be overwritten")


def stored_score(measurement: Measurement, version: str) -> HealthScoreOut | None:
    row = next((item for item in measurement.health_scores if item.score_version == version), None)
    return HealthScoreOut.model_validate(row.result | {"created_at": row.created_at}) if row else None


def store_score(db: Session, measurement: Measurement, config: ScoreConfig) -> HealthScoreOut:
    existing = stored_score(measurement, config.score_version)
    if existing:
        if existing.config_hash != config_hash(config):
            raise ValueError("existing score uses a different config; change score_version")
        return existing
    payload = {"metrics": measurement.metrics, "collector_status": measurement.collector_status}
    result = calculate_score(payload, config, measurement.id)
    row = HealthScore(measurement=measurement, score_version=config.score_version, config_hash=result.config_hash,
                      config_snapshot=config.model_dump(), overall_score=result.overall.score,
                      overall_severity=result.overall.severity, result=result.model_dump(mode="json"))
    db.add(row)
    db.flush()
    return HealthScoreOut.model_validate(row.result | {"created_at": row.created_at})
