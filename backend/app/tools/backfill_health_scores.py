"""Insert immutable score rows only. Default is a read-only dry run."""
import argparse
import csv
from pathlib import Path
from statistics import mean

from sqlalchemy import inspect, select
from sqlalchemy.orm import noload

from ..config import settings
from ..db import SessionLocal, engine
from ..models import HealthScore, Measurement
from ..score_store import store_score, stored_score, validate_stored_policy
from ..scoring import calculate_score, load_score_config


EXPERIMENT_AGENT = "549dc09b-4438-4e02-ad3b-2e70c4110b95"
CONDITIONS = ("NORMAL", "HIGH_LATENCY", "PACKET_LOSS", "MIXED")


def backfill(db, config, start_id, end_id, agent_id, apply=False):
    if start_id < 1 or end_id < start_id:
        raise ValueError("invalid measurement range")
    has_scores = inspect(db.get_bind()).has_table("health_scores")
    if apply and not has_scores:
        raise ValueError("start the v2 backend first to create the health_scores table")
    query = select(Measurement).where(Measurement.id.between(start_id, end_id)).order_by(Measurement.id)
    if not has_scores:
        query = query.options(noload(Measurement.health_scores))
    rows = db.scalars(query).all()
    if [row.id for row in rows] != list(range(start_id, end_id + 1)):
        raise ValueError("range is incomplete; no partial backfill will be performed")
    if any(row.agent_id != agent_id for row in rows):
        raise ValueError("agent mismatch; no score will be inserted")
    if has_scores:
        validate_stored_policy(db, config)
    results, inserted = [], 0
    for row in rows:
        existing = stored_score(row, config.score_version) if has_scores else None
        if existing:
            result = existing
        elif apply:
            result = store_score(db, row, config)
            inserted += 1
        else:
            result = calculate_score({"metrics": row.metrics, "collector_status": row.collector_status}, config, row.id)
        results.append(result)
    return results, inserted


def write_experiment_csv(results, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for result in results:
        condition = CONDITIONS[(result.measurement_id - 21) // 5] if 21 <= result.measurement_id <= 40 else "UNLABELED"
        cause = result.top_causes[0] if result.top_causes else None
        rows.append({"measurement_id": result.measurement_id, "condition": condition, "overall": result.overall.score,
                     **{name: value.score for name, value in result.categories.items()},
                     "top_deduction": f"{cause.category}: {cause.metric}={cause.value:g}{cause.unit} -{cause.points}" if cause else "none",
                     "overall_coverage": result.overall.coverage, "score_version": result.score_version, "config_hash": result.config_hash})
    fields = ["measurement_id", "condition", "overall", "local", "internet", "dns", "tcp", "http", "top_deduction", "overall_coverage", "score_version", "config_hash"]

    def write(target, columns, data):
        with target.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows({key: "null" if row.get(key) is None else row[key] for key in columns} for row in data)

    write(path, fields, rows)
    write(path.with_name("health_score_representatives.csv"), fields, [row for row in rows if row["measurement_id"] in (22, 26, 31, 36)])
    summaries = []
    for condition in CONDITIONS:
        subset = [row for row in rows if row["condition"] == condition]
        if not subset:
            continue
        summary = {"condition": condition, "measurement_n": len(subset)}
        for field in ("overall", "local", "internet", "dns", "tcp", "http"):
            values = [row[field] for row in subset if row[field] is not None]
            summary[field] = round(mean(values), 2) if values else None
            summary[field + "_n"] = len(values)
        summaries.append(summary)
    write(path.with_name("health_score_summary.csv"), list(summaries[0]) if summaries else ["condition"], summaries)
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-id", type=int, default=21)
    parser.add_argument("--end-id", type=int, default=40)
    parser.add_argument("--agent-id", default=EXPERIMENT_AGENT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args()
    config = load_score_config(settings.health_score_path)
    with SessionLocal() as db:
        results, inserted = backfill(db, config, args.start_id, args.end_id, args.agent_id, apply=args.apply)
        if args.apply:
            db.commit()
    print(f"mode={'apply' if args.apply else 'dry-run'} rows={len(results)} inserted={inserted} version={config.score_version}")
    for result in results:
        print(f"ID {result.measurement_id}: overall={result.overall.score} " + " ".join(f"{name}={value.score}" for name, value in result.categories.items()))
    if args.csv:
        for summary in write_experiment_csv(results, args.csv):
            print(summary)


if __name__ == "__main__":
    main()
