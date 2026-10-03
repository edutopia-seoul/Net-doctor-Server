# NetDoctor Server

Agent가 보낸 구조화된 네트워크 측정값을 PostgreSQL에 저장하고, YAML 기반 Rule Engine과 Ollama Local LLM으로 진단하는 FastAPI + React 서버입니다. AI는 입력 측정값을 생성하지 않고, 측정 사실·규칙 결과·가설을 분리합니다.

## Architecture

```text
Agent --X-NetDoctor-Key--> FastAPI :8000 --> PostgreSQL
                              |                 |
                              +--> Rule Engine  +--> diagnosis history
                              +--> Ollama host:11434
Browser --> React/Nginx :3001 --/api/--> FastAPI
```

## Requirements

- Docker Engine and Docker Compose
- Host Ollama (GPU/driver가 안정적인 기존 서비스를 사용)
- Ollama model: `qwen3.5:4b-q4_K_M`

## Installation and run

```bash
cp .env.example .env
# openssl rand -hex 32 등으로 POSTGRES_PASSWORD와 AGENT_API_KEY를 각각 새로 만들어 .env에 입력
chmod 600 .env
docker compose up -d --build
curl http://127.0.0.1:8000/health
```

PostgreSQL은 `127.0.0.1:5432`에만 바인딩합니다. Backend와 Frontend는 host network를 사용해 기존 Ollama와 서로 통신합니다. 기존 3000번 서비스와 충돌하지 않도록 Dashboard는 3001번입니다.

## Environment variables

`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `AGENT_API_KEY`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`을 `.env`에서 지정합니다. 현재 Ollama는 `192.168.0.201:11434`에서 실행 중입니다. `.env`는 Git에 포함하지 않습니다.

## API

모든 `/api/v1/*` 요청은 `X-NetDoctor-Key` header가 필요합니다. 등록과 측정 규격은 프로젝트 지시서의 JSON을 그대로 사용합니다.

- `GET /health`
- `POST /api/v1/agents/register`
- `GET /api/v1/agents`, `GET /api/v1/agents/{agent_id}`
- `POST /api/v1/measurements`
- `GET /api/v1/measurements`, `GET /api/v1/measurements/{id}`
- `GET /api/v1/measurements/{id}/health-score`
- `GET /api/v1/diagnoses`, `GET /api/v1/diagnoses/{id}`
- `GET /api/v1/agents/{agent_id}/history`
- Swagger: `http://127.0.0.1:8000/docs`

## Dashboard

`http://127.0.0.1:3001`에서 한글 대시보드의 개요, 측정 상세, AI 진단, 이력 탭을 확인합니다. 외부 Caddy 경로는 `https://ikeawolf.duckdns.org:51739/NetDoctorServer/`입니다(Caddy 인증 필요). 화면의 API 키 입력란에 `.env`의 `AGENT_API_KEY`를 입력합니다. 키는 브라우저 탭의 sessionStorage에만 보관하며 JavaScript 번들에는 포함하지 않습니다. 과거에 저장된 AI 자유 서술은 영문으로 남을 수 있으나, 새 AI 진단은 한글로 요청합니다.

Frontend는 React/Vite와 Bklit Line/Area Chart, Tailwind CSS로 구성됩니다. 실제 Agent의 마지막 측정을 기준으로 Health Score와 영역별 감점 근거, Rule 경보, Gateway/Internet RTT, 손실률, System DNS, HTTP TTFB, TCP 재전송률을 표시합니다. 최근 20/50/100건의 시간순 이력과 점수 차트, 측정 상세, 사실·규칙·AI 가설·권장 조치 분리, 밝은/어두운 테마를 제공합니다. 결측값은 0으로 대체하지 않습니다. 실험 label 필드는 없어 임의 생성하지 않습니다. Agent 상태는 heartbeat가 아니라 마지막 수신 시각으로 표시합니다.

## Network Health Score

Health Score는 **실측값 → YAML 정량 기준 → 감점 → 점수**로 계산하는 NetDoctor 내부의 설명 가능한 품질 지표입니다. 의료·통신사업자의 공식 품질 기준 또는 SLA 인증이 아닙니다. AI가 점수를 생성하거나 수정하지 않습니다.

현재 기본 정책은 **`health-score-v1.1`**, 설정은 [health_score_v1_1.yaml](backend/app/health_score_v1_1.yaml)입니다. Pydantic으로 가중치·경계·감점을 시작 시 검증합니다. 기존 [health_score.yaml](backend/app/health_score.yaml)의 `health-score-v1` 정책 및 저장 결과는 그대로 보존합니다. 기존 Rule YAML과 Agent 입력 schema는 바꾸지 않습니다.

### Score / Status / Data Quality

- **Score**: 0~100의 전체 품질 가중 평균. 점수 기준 `base_severity`는 80 이상 normal, 60 이상 80 미만 warning, 60 미만 critical입니다.
- **Status**: 점수 기준 상태와 Severity Guard 중 더 심각한 상태입니다. Category가 60 미만이면 최소 warning, 40 미만인 심각한 영역도 최소 warning입니다. 기존 Rule warning은 최소 warning, Rule critical은 critical을 강제합니다. Guard는 **숫자 점수를 낮추지 않습니다**. 따라서 실험 #34의 `82.75점 / WARNING`은 의도된 결과입니다.
- **Data Quality**: `complete` / `partial` / `low_confidence` / `unavailable`. TCP 작은 표본이 있으면 Overall은 low_confidence이며, 점수나 장애 상태와는 별개입니다. 부분 측정에 작은 표본까지 있는 경우에는 low_confidence를 우선 표시하고 coverage와 결측 근거를 함께 제공합니다.

API의 `overall.score`, `overall.base_severity`, `overall.status`, `overall.guard_triggered`, `overall.guard_reason`, `overall.quality`를 각각 사용합니다. 호환 필드 `overall.severity`는 v1.1에서 최종 Status와 같습니다. 기존 v1은 점수 기준 severity 그대로이며 새 상태 필드가 없는 저장 결과도 조회할 수 있습니다.

| 영역 | 가중치 | 사용하는 지표 |
|---|---:|---|
| Local | 20% | Gateway RTT, Gateway Loss |
| Internet | 25% | Internet RTT, Internet Loss |
| DNS | 15% | System/Google/Cloudflare 응답 시간 |
| TCP | 20% | 재전송률, Duplicate ACK, RST, Zero Window; 캡처 표본 표시 |
| HTTP | 20% | 상태 코드, TTFB, Total, Connect, TLS |

도달성·전송 품질(Local/Internet/TCP)에 합계 65%, DNS에 15%, 사용자 요청 결과(HTTP)에 20%를 배정합니다. 가중치 합은 1.0이고 각 값은 양수여야 합니다. 독립적인 물리 고장 확률이나 통계 학습 가중치는 아닙니다.

- 영역은 100점에서 시작합니다. v1은 기존 단계형 정책을 유지합니다. v1.1은 다음 **6개 Metric만 구간 선형 보간**하고 나머지는 단계형으로 유지합니다. `(실측값−구간 시작)/(구간 끝−구간 시작)`의 비율로 두 감점 anchor 사이를 보간하며, 마지막 anchor 이후에는 감점 상한을 유지합니다. 기존 양수 경계/감점 anchor는 그대로 사용하고, 0점 감점 시작은 첫 경계의 절반(손실은 0%)으로 정했습니다. 실제 20건의 결과에 맞춰 경계를 조정하지 않았습니다.

| 선형 Metric | 감점 시작(감점 0) | 기존 경계→감점 anchor |
|---|---:|---|
| Gateway RTT(ms) | 10 | 20→25, 100→40, 200→50, 500→65 |
| Internet RTT(ms) | 75 | 150→30, 200→50, 500→65 |
| Gateway / Internet Loss(%) | 0 | 3→25, 5→35, 10→45, 20→60, 50→75, 100→100 |
| TCP retransmission(%) | 0.5 | 1→10, 5→25, 10→40, 20→60, 50→80, 100→100 |
| HTTP TTFB(ms) | 400 | 800→25, 1500→40, 3000→60 |

- 실제 Loss 0%는 감점하지 않습니다. TTFB 799→801ms처럼 경계를 넘을 때 큰 점프가 나지 않습니다. Score의 상태 구간(80/60)과 Rule의 기존 경계까지 연속식으로 바꾼 것은 아닙니다.
- DNS 서버별 지연, HTTP의 겹치는 시간 지표, TCP 재전송·중복 ACK는 각각 같은 그룹의 **최대 감점 1개**만 적용합니다. 나머지 독립 그룹을 합하되 0점에서 제한하고 실제 적용 감점을 저장합니다. `100−감점 합계=영역 점수`가 항상 성립합니다.
- 각 감점은 `code`, 원본 `metric`, 실제 `value`, `unit`, 적용 `points`, 상한 적용 전 `assessed_points`, `reason`, `group`을 제공합니다. 단계형은 `threshold`/`operator`, 선형은 `calculation=linear`과 `range_start`/`range_end`로 감점 구간을 추적합니다. 소수 감점은 4자리, Overall은 2자리로 저장합니다. `top_causes.weighted_points`는 전체 점수에 반영된 감점입니다.
- `cause_group`은 LATENCY / LATENCY_EFFECT, PACKET_LOSS / TCP_DEGRADATION 등을 설명용으로 묶습니다. 여러 Category에 나타난 관련 효과는 점수에 남되 독립 장애 여러 개로 단정하지 않습니다. 인과관계를 증명하거나 Category 간 숫자 감점을 상쇄하는 기능은 아닙니다.
- TCP RST 1건은 감점하지 않습니다. 반복 RST≥5와 재전송≥5%, Duplicate ACK≥3, Zero Window≥1 중 하나가 함께 관측된 경우에만 25점 감점합니다. RST 자체가 특정 장비 장애의 확정 근거는 아닙니다.
- `null`, 비유한 수, 음수, 설정 유효 범위 위반은 제외합니다. 유효 성능 지표가 없는 영역은 `score=null`, `available=false`입니다. Capture 0개도 TCP 점수를 계산하지 않습니다. `coverage`는 영역의 설정 지표 중 유효 비율입니다. TCP 표본 50개 미만 또는 미확인은 v1.1에서 `quality=low_sample`, `sample_size`로 표시하며 그 자체로 감점하거나 TCP 가중치를 제거하지 않습니다.
- Cloudflare 직접 질의 실패만으로 DNS 전체를 감점하지 않습니다. 성공한 resolver 시간으로 점수를 계산하되 결측·collector partial을 표시합니다. System DNS가 없으면 클라이언트의 DNS 품질이 검증됐다고 해석하지 않습니다. 저장된 실제 0ms는 그대로 유지합니다.
- Overall은 유효 영역만 가중치를 정규화한 평균이며, 유효 영역의 원래 가중치 합이 0.50 이상이어야 제공됩니다. Overall coverage는 누락 영역을 포함한 원래 가중치로 계산합니다. 부분 데이터에서 높은 점수가 나와도 coverage/quality를 함께 읽어야 합니다.
- v1에 없는 Link/Interface 상태는 추측하지 않습니다. Traceroute timeout/hop 수만으로 감점하지 않습니다. HTTP 수집 실패로 측정값이 없으면 원격 서버 장애를 단정하지 않고 계산 불가/부분 측정으로 처리합니다. HTTP 4xx/5xx가 실제 저장된 경우는 상태 코드 감점을 적용합니다. 높은 TTFB에는 네트워크와 서버 처리 요인이 섞입니다. RST는 정상 연결 종료에서도 관측될 수 있습니다.

`health_scores` 테이블은 `(measurement_id, score_version)`별 불변 결과, 전체/영역 점수, 감점, YAML snapshot/hash, 생성 시각을 저장합니다. 별도 DB 스키마 변경 없이 JSONB에 새 근거 필드를 저장합니다. 정책 변경 시 `score_version`을 바꾸고 Backend를 재빌드하세요. 동일 버전으로 YAML을 변경해 기존 결과를 덮어쓰는 작업은 거부합니다. v1.1의 Hash는 key 순서와 정수/실수 표기(0/0.0)를 canonical JSON으로 정규화합니다. 기존 v1 Hash는 기존 직렬화 방식으로 유지합니다.

API: `GET /api/v1/measurements/{id}/health-score`는 동일한 `X-NetDoctor-Key` 인증을 사용합니다. 기본은 활성 v1.1이며 `?score_version=health-score-v1`로 기존 결과를 선택합니다. Measurement 목록/상세, Diagnosis 목록/상세, Agent History에도 동일한 optional query가 있습니다. 기존 Measurement/Diagnosis의 Measurement 객체와 History에 optional `health_score`가 제공됩니다. 미계산 Measurement의 필드는 null이고 별도 점수 API는 404입니다. GET 요청은 점수를 새로 저장하지 않습니다. 신규 업로드는 Rule과 Score를 AI 호출 전에 저장하며 Ollama 장애 시에도 둘 다 제공합니다.

기존 실험 Backfill은 기본 dry-run입니다. 범위와 Agent를 확인한 후 신규 Score만 INSERT하고 기존 Measurement/Rule/AI는 수정하지 않습니다.

```bash
docker compose build backend frontend
docker compose up -d --no-deps backend frontend
docker compose exec -T backend python -m app.tools.backfill_health_scores --dry-run
docker compose exec -T backend python -m app.tools.backfill_health_scores --apply
```

두 버전이 이미 저장된 경우 다음 조회/내보내기는 DB를 변경하지 않습니다. Backend 컨테이너는 Compose가 구성한 PostgreSQL URL을 사용하므로 비밀번호를 별도로 출력하거나 입력할 필요가 없습니다.

```bash
docker compose exec -T backend python -m app.tools.backfill_health_scores \
  --dry-run --comparison-csv /tmp/health_score_v1_vs_v1_1.csv
docker compose cp backend:/tmp/health_score_v1_vs_v1_1.csv reports/health_score_v1_vs_v1_1.csv
# 기존 v1 정책을 명시적으로 검증/조회
docker compose exec -T backend python -m app.tools.backfill_health_scores \
  --dry-run --config /app/app/health_score.yaml
```

DB URL의 비밀번호를 출력하거나 셸 이력에 직접 적지 마세요. Host Python으로 실행할 때는 기본 SQLite가 아닌 운영 PostgreSQL `DATABASE_URL`을 비공개로 제공해야 합니다. 이미 계산한 범위의 재실행은 0건 INSERT입니다. 기본 범위는 실제 Agent ID의 21~40이며, Guard Backfill은 모든 측정의 **기존 Rule 결과가 있어야** 수행합니다. v1 CSV인 `health_score_experiment.csv`, `health_score_summary.csv`, `health_score_representatives.csv`는 보존합니다. v1.1 별도 통계 CSV가 필요하면 `--csv /tmp/health_score_v1_1_experiment.csv`를 지정한 뒤 복사합니다. 새 버전의 companion CSV는 지정 이름에 `_summary`/`_representatives`를 붙여 v1 파일을 덮어쓰지 않습니다. 조건 이름은 사용자 제공 실험 mapping으로 CSV에만 붙이며 Measurement에 새 label을 기록하지 않습니다.

Dashboard의 “점수 정책”에서 v1.1/v1을 전환합니다. 개요/측정 상세의 Score·Status·Data Quality를 분리하고, 영역 카드를 클릭하면 점수→감점→원본 필드/값/보간 구간까지 확인할 수 있습니다. DNS 100점은 **측정된 Resolver에서 지연 감점이 없었다**는 뜻이며 모든 Resolver가 정상이라는 의미가 아닙니다. 기존 Rule 경보와 AI 진단은 유지하고, History와 최근 측정 표는 선택한 버전의 DB 저장 점수만 표시합니다. 신규 AI 요청에는 읽기 전용 점수·상태·품질·Guard 근거를 제공하며 기존 AI 결과는 다시 생성하지 않습니다.

Agent는 `http://192.168.0.201:8000`을 Server URL로 사용하고, 모든 `/api/v1/*` 요청에 `X-NetDoctor-Key: <AGENT_API_KEY>`를 보냅니다. 먼저 `POST /api/v1/agents/register`, 이후 `POST /api/v1/measurements` 순서입니다. 실제 Ubuntu Agent(`192.168.0.202`)의 측정 11건으로 DB·규칙·AI·이력을 검증했습니다. 현재 AI 요청은 동기식이며 Host Ollama 추론이 느리므로 여러 측정을 한꺼번에 보내지 말고 각 요청 완료를 기다리세요. 실험 전 Agent와 Server의 시계를 동기화하세요.

## Tests

```bash
uv venv
uv pip install --python .venv/bin/python -r backend/requirements.txt
PYTHONPATH=backend .venv/bin/pytest -q backend/tests
cd frontend && npm ci && npm test && npm run build
```

Frontend만 반영할 때는 프로젝트 루트에서 `docker compose build frontend` 후 `docker compose up -d --no-deps frontend`를 실행합니다. API endpoint와 Backend는 변경하지 않습니다.

## Backup and stop

```bash
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > netdoctor.sql
docker compose down
```

## Troubleshooting

```bash
docker compose ps
docker compose logs backend
curl http://192.168.0.201:11434/api/tags
```

Ollama가 중단되면 측정 저장과 Rule Diagnosis는 계속되고, AI 결과는 `available=false`와 `AI analysis unavailable - rule-based diagnosis is still available.`로 반환됩니다. 모델을 바꾸려면 `OLLAMA_MODEL`만 변경합니다. 현재 호스트의 GPU NVML 드라이버 불일치 때문에 Ollama를 별도 Container로 실행하지 않습니다.
