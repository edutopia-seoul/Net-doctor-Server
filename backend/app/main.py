from datetime import datetime, timezone
from secrets import compare_digest

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .ai import _measured_facts, analyze
from .config import settings
from .db import Base, engine, get_db
from .models import AIDiagnosis, Agent, Measurement, RuleDiagnosis
from .rule_engine import diagnose
from .schemas import AgentOut, AgentRegister, AIDiagnosisOut, DiagnosisOut, HealthScoreOut, MeasurementIn, MeasurementOut, RuleDiagnosisOut
from .score_store import store_score, stored_score, validate_stored_policy
from .scoring import load_score_config


app = FastAPI(title="NetDoctor Server", version="0.2.0")


@app.on_event("startup")
def startup():
    config = load_score_config(settings.health_score_path)
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        validate_stored_policy(db, config)


def auth(x_netdoctor_key: str | None = Header(default=None)):
    if not x_netdoctor_key or not compare_digest(x_netdoctor_key, settings.agent_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")


def measurement_out(row: Measurement) -> MeasurementOut:
    return MeasurementOut(id=row.id, agent_id=row.agent_id, timestamp=row.timestamp, target_profile=row.target_profile,
                          network=row.network, metrics=row.metrics, collector_status=row.collector_status, created_at=row.created_at,
                          health_score=stored_score(row, load_score_config(settings.health_score_path).score_version))


def diagnosis_out(measurement: Measurement) -> DiagnosisOut:
    rule, ai = measurement.rule_diagnosis, measurement.ai_diagnosis
    return DiagnosisOut(
        measurement=measurement_out(measurement),
        rule_diagnosis=RuleDiagnosisOut(severity=rule.severity, findings=rule.findings, triggered_rules=rule.triggered_rules),
        ai_diagnosis=AIDiagnosisOut(available=ai.available, severity=ai.severity, primary_cause=ai.primary_cause,
                                    confidence=ai.confidence, measured_facts=ai.measured_facts, rule_findings=ai.rule_findings,
                                    hypotheses=ai.hypotheses, impact=ai.impact, recommendations=ai.recommendations,
                                    additional_checks=ai.additional_checks, model=ai.model, error=ai.error),
    )


@app.get("/health")
def health():
    return {"status": "ok", "service": "netdoctor-server", "server_time": datetime.now(timezone.utc).isoformat()}


@app.post("/api/v1/agents/register", dependencies=[Depends(auth)])
def register_agent(payload: AgentRegister, db: Session = Depends(get_db)):
    row = db.scalar(select(Agent).where(Agent.agent_id == payload.agent_id))
    now = datetime.now(timezone.utc)
    metadata = {"interfaces": [i.model_dump() for i in payload.interfaces], "capabilities": payload.capabilities}
    if row:
        row.hostname, row.os, row.agent_version, row.last_seen, row.metadata_json = payload.hostname, payload.os, payload.agent_version, now, metadata
    else:
        row = Agent(agent_id=payload.agent_id, hostname=payload.hostname, os=payload.os, agent_version=payload.agent_version,
                    last_seen=now, metadata_json=metadata)
        db.add(row)
    db.commit()
    return {"status": "ok", "agent_id": row.agent_id, "server_time": now.isoformat()}


@app.get("/api/v1/agents", response_model=list[AgentOut], dependencies=[Depends(auth)])
def list_agents(db: Session = Depends(get_db)):
    rows = db.scalars(select(Agent).order_by(desc(Agent.last_seen))).all()
    return [AgentOut(agent_id=r.agent_id, hostname=r.hostname, os=r.os, agent_version=r.agent_version, last_seen=r.last_seen,
                     created_at=r.created_at, metadata=r.metadata_json) for r in rows]


@app.get("/api/v1/agents/{agent_id}", response_model=AgentOut, dependencies=[Depends(auth)])
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    row = db.scalar(select(Agent).where(Agent.agent_id == agent_id))
    if not row:
        raise HTTPException(404, "agent not found")
    return AgentOut(agent_id=row.agent_id, hostname=row.hostname, os=row.os, agent_version=row.agent_version,
                    last_seen=row.last_seen, created_at=row.created_at, metadata=row.metadata_json)


@app.post("/api/v1/measurements", response_model=MeasurementOut, dependencies=[Depends(auth)])
def create_measurement(payload: MeasurementIn, db: Session = Depends(get_db)):
    agent = db.scalar(select(Agent).where(Agent.agent_id == payload.agent_id))
    if not agent:
        raise HTTPException(404, "agent must be registered first")
    agent.last_seen = datetime.now(timezone.utc)
    raw = payload.model_dump(mode="json")
    row = Measurement(agent_id=payload.agent_id, timestamp=payload.timestamp, target_profile=raw["target_profile"],
                      network=raw["network"], metrics=raw["metrics"], collector_status=raw["collector_status"])
    db.add(row)
    db.flush()
    rule = diagnose(raw["metrics"], settings.rules_path)
    db.add(RuleDiagnosis(measurement_id=row.id, **rule))
    score = store_score(db, row, load_score_config(settings.health_score_path))
    db.commit()
    db.refresh(row)
    history_rows = db.scalars(select(Measurement).where(Measurement.agent_id == payload.agent_id).order_by(desc(Measurement.timestamp)).limit(5)).all()
    history = [{"timestamp": h.timestamp.isoformat(), "metrics": {"gateway_ping": h.metrics.get("gateway_ping"),
                                                                    "internet_ping": h.metrics.get("internet_ping"),
                                                                    "dns": h.metrics.get("dns")}} for h in history_rows if h.id != row.id][:4]
    score_context = {"score_version": score.score_version, "overall": score.overall.model_dump(),
                     "categories": {name: {"score": value.score, "coverage": value.coverage} for name, value in score.categories.items()},
                     "main_deductions": [cause.model_dump() for cause in score.top_causes[:5]]}
    result, error = analyze(raw | {"health_score": score_context}, rule, history)
    if result:
        db.add(AIDiagnosis(measurement_id=row.id, available=True, severity=result.severity, primary_cause=result.primary_cause,
                           confidence=result.confidence, measured_facts=result.measured_facts, rule_findings=result.rule_findings,
                           hypotheses=result.hypotheses, impact=result.impact, recommendations=result.recommendations,
                           additional_checks=result.additional_checks, model=settings.ollama_model))
    else:
        db.add(AIDiagnosis(measurement_id=row.id, available=False, error=error, model=settings.ollama_model,
                           severity=rule["severity"], measured_facts=_measured_facts(raw), rule_findings=rule["findings"],
                           recommendations=["AI analysis unavailable - rule-based diagnosis is still available."]))
    db.commit()
    return measurement_out(row)


@app.get("/api/v1/measurements", response_model=list[MeasurementOut], dependencies=[Depends(auth)])
def list_measurements(agent_id: str | None = None, limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    query = select(Measurement).order_by(desc(Measurement.timestamp)).limit(limit)
    if agent_id:
        query = query.where(Measurement.agent_id == agent_id)
    return [measurement_out(r) for r in db.scalars(query).all()]


@app.get("/api/v1/measurements/{measurement_id}", response_model=MeasurementOut, dependencies=[Depends(auth)])
def get_measurement(measurement_id: int, db: Session = Depends(get_db)):
    row = db.get(Measurement, measurement_id)
    if not row:
        raise HTTPException(404, "measurement not found")
    return measurement_out(row)


@app.get("/api/v1/measurements/{measurement_id}/health-score", response_model=HealthScoreOut, dependencies=[Depends(auth)])
def get_health_score(measurement_id: int, db: Session = Depends(get_db)):
    row = db.get(Measurement, measurement_id)
    if not row:
        raise HTTPException(404, "measurement not found")
    result = stored_score(row, load_score_config(settings.health_score_path).score_version)
    if not result:
        raise HTTPException(404, "health score not backfilled for the active version")
    return result


@app.get("/api/v1/diagnoses", response_model=list[DiagnosisOut], dependencies=[Depends(auth)])
def list_diagnoses(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    rows = db.scalars(select(Measurement).order_by(desc(Measurement.timestamp)).limit(limit)).all()
    return [diagnosis_out(row) for row in rows if row.rule_diagnosis and row.ai_diagnosis]


@app.get("/api/v1/diagnoses/{measurement_id}", response_model=DiagnosisOut, dependencies=[Depends(auth)])
def get_diagnosis(measurement_id: int, db: Session = Depends(get_db)):
    row = db.get(Measurement, measurement_id)
    if not row or not row.rule_diagnosis or not row.ai_diagnosis:
        raise HTTPException(404, "diagnosis not found")
    return diagnosis_out(row)


@app.get("/api/v1/agents/{agent_id}/history", response_model=list[MeasurementOut], dependencies=[Depends(auth)])
def agent_history(agent_id: str, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    rows = db.scalars(select(Measurement).where(Measurement.agent_id == agent_id).order_by(desc(Measurement.timestamp)).limit(limit)).all()
    return [measurement_out(r) for r in reversed(rows)]
