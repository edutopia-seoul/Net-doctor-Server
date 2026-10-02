"""Deterministic quality scores; missing collectors are not invented performance faults."""
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schemas import CategoryScore, HealthScoreOut, OverallScore, ScoreCause, ScoreDeduction


CATEGORIES = {"local", "internet", "dns", "tcp", "http"}


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Band(ConfigModel):
    threshold: float = Field(ge=0)
    points: int = Field(gt=0, le=100)


class MetricPolicy(ConfigModel):
    code: str = Field(min_length=1)
    unit: str
    operator: Literal["ge", "gt"] = "ge"
    group: str | None = None
    minimum: float = Field(default=0, ge=0)
    maximum: float | None = Field(default=None, ge=0)
    integer: bool = False
    bands: list[Band] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_bands(self):
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("metric range is invalid")
        if any(a.threshold >= b.threshold or a.points > b.points for a, b in zip(self.bands, self.bands[1:])):
            raise ValueError("bands must have increasing thresholds and nondecreasing deductions")
        if any(b.threshold < self.minimum or (self.maximum is not None and b.threshold > self.maximum) for b in self.bands):
            raise ValueError("threshold is outside metric range")
        return self


class CategoryPolicy(ConfigModel):
    collectors: list[str] = Field(default_factory=list)
    metrics: dict[str, MetricPolicy] = Field(min_length=1)


class SeverityPolicy(ConfigModel):
    normal_min: float = Field(ge=0, le=100)
    warning_min: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def ordered_levels(self):
        if self.warning_min >= self.normal_min:
            raise ValueError("warning_min must be below normal_min")
        return self


class ScoreConfig(ConfigModel):
    score_version: str = Field(min_length=1, max_length=64)
    weights: dict[str, float]
    severity: SeverityPolicy
    minimum_available_weight: float = Field(gt=0, le=1)
    tcp_min_packets: int = Field(gt=0)
    categories: dict[str, CategoryPolicy]

    @model_validator(mode="after")
    def valid_weights(self):
        if set(self.weights) != CATEGORIES or set(self.categories) != CATEGORIES:
            raise ValueError("exactly five category policies/weights are required")
        if any(not math.isfinite(w) or w <= 0 for w in self.weights.values()) or not math.isclose(sum(self.weights.values()), 1, abs_tol=1e-9):
            raise ValueError("positive finite weights must sum to 1.0")
        for category in self.categories.values():
            if any(path.count(".") != 1 for path in category.metrics):
                raise ValueError("metric paths must be section.field")
        return self


@lru_cache(maxsize=4)
def load_score_config(path: str | None = None) -> ScoreConfig:
    source = Path(path) if path else Path(__file__).with_name("health_score.yaml")
    return ScoreConfig.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))


def config_hash(config: ScoreConfig) -> str:
    return hashlib.sha256(json.dumps(config.model_dump(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def score_severity(score: float | None, config: ScoreConfig) -> str:
    if score is None:
        return "unknown"
    return "normal" if score >= config.severity.normal_min else "warning" if score >= config.severity.warning_min else "critical"


def metric_value(metrics: dict, path: str):
    section, field = path.split(".")
    return (metrics.get(section) or {}).get(field)


def valid_number(value, policy: MetricPolicy | None = None) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return False
    return not policy or (value >= policy.minimum and (policy.maximum is None or value <= policy.maximum)
                          and (not policy.integer or float(value).is_integer()))


def calculate_score(measurement: dict, config: ScoreConfig, measurement_id: int | None = None) -> HealthScoreOut:
    metrics = measurement.get("metrics") or {}
    categories = {}
    for name, category in config.categories.items():
        evidence, missing, groups, notes = {}, [], {}, []
        for path, policy in category.metrics.items():
            value = metric_value(metrics, path)
            if not valid_number(value, policy):
                missing.append(path)
                continue
            evidence[path] = value
            band = next((b for b in reversed(policy.bands) if value > b.threshold or (policy.operator == "ge" and value == b.threshold)), None)
            if not band:
                continue
            group = policy.group or path
            symbol = ">" if policy.operator == "gt" else "≥"
            deduction = ScoreDeduction(code=policy.code, metric=path, value=value, unit=policy.unit,
                                      threshold=band.threshold, operator=policy.operator, group=group,
                                      points=band.points, assessed_points=band.points,
                                      reason=f"{path} 실측 {value:g} {policy.unit}: 설정 기준 {symbol} {band.threshold:g} {policy.unit}")
            if group not in groups or groups[group].points < deduction.points:
                groups[group] = deduction
        for collector in measurement.get("collector_status") or []:
            if collector.get("name") in category.collectors and collector.get("status") != "ok":
                notes.append(f"{collector['name']} 수집 상태: {collector.get('status')} (성능 감점과 구분)")
        if missing:
            notes.append("결측·유효하지 않은 지표는 점수 입력에서 제외합니다.")
        low_sample = False
        if name == "tcp":
            count = metric_value(metrics, "tcp.captured_packets")
            low_sample = not valid_number(count) or count < config.tcp_min_packets
            if valid_number(count):
                evidence["tcp.captured_packets"] = count
            if low_sample:
                notes.append(f"TCP 유효 표본이 {config.tcp_min_packets}개 미만이거나 확인되지 않아 해석 신뢰도가 낮습니다.")
            if count == 0:
                # No packets cannot support a measured zero retransmission rate.
                groups, evidence = {}, {"tcp.captured_packets": 0}
                missing = list(category.metrics)
        available = len(missing) < len(category.metrics)
        deductions = sorted(groups.values(), key=lambda d: (-d.points, d.metric))
        applied, remaining = [], 100
        for deduction in deductions:
            deduction = deduction.model_copy(update={"points": min(deduction.points, remaining)})
            remaining -= deduction.points
            if deduction.points:
                applied.append(deduction)
        score = remaining if available else None
        coverage = round((len(category.metrics) - len(missing)) / len(category.metrics), 4)
        categories[name] = CategoryScore(score=score, severity=score_severity(score, config), available=available,
                                        coverage=coverage, quality="unavailable" if not available else "partial" if notes or low_sample else "complete",
                                        low_sample=low_sample, evidence=evidence, missing_metrics=missing, notes=notes, deductions=applied)
    included = sum(config.weights[name] for name, category in categories.items() if category.available)
    coverage = sum(config.weights[name] * category.coverage for name, category in categories.items())
    available = included >= config.minimum_available_weight
    score = round(sum(category.score * config.weights[name] for name, category in categories.items() if category.available) / included, 2) if available else None
    partial = any(category.quality != "complete" for category in categories.values())
    notes = ["측정 범위/표본 제한이 있습니다. 점수는 수집된 지표에 대한 평가입니다."] if partial else []
    if included < 1:
        notes.append("계산 불가 영역의 가중치를 제외하고 나머지를 정규화했습니다.")
    if not available:
        notes.append("유효 영역 가중치가 최소 기준에 미달해 전체 점수를 제공하지 않습니다.")
    causes = [ScoreCause(**deduction.model_dump(), category=name,
                         weighted_points=round(deduction.points * config.weights[name] / included, 4))
              for name, category in categories.items() for deduction in category.deductions] if included else []
    return HealthScoreOut(measurement_id=measurement_id, score_version=config.score_version, config_hash=config_hash(config),
                          weights=config.weights, categories=categories,
                          overall=OverallScore(score=score, severity=score_severity(score, config), available=available,
                                               coverage=round(coverage, 4), included_weight=round(included, 4),
                                               quality="unavailable" if not available else "partial" if partial else "complete", notes=notes),
                          top_causes=sorted(causes, key=lambda cause: (-cause.weighted_points, cause.category, cause.metric)))
