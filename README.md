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

`backend/app/health_score.yaml`의 모든 가중치·경계·감점은 Pydantic으로 시작 시 검증합니다. 기본 정책은 `health-score-v1`. 기존 Rule YAML과 Agent 입력 schema는 유지합니다. 품질 점수의 severity는 80~100 `normal`, 60~79.99 `warning`, 0~59.99 `critical`입니다. 단일 Rule 경보와 종합 가중 평균은 의미가 달라 화면에서 별도로 표시합니다. Overall이 normal이어도 특정 영역의 warning/critical 근거가 있으면 해당 Rule 경보를 함께 확인하세요.

| 영역 | 가중치 | 사용하는 지표 |
|---|---:|---|
| Local | 20% | Gateway RTT, Gateway Loss |
| Internet | 25% | Internet RTT, Internet Loss |
| DNS | 15% | System/Google/Cloudflare 응답 시간 |
| TCP | 20% | 재전송률, Duplicate ACK, RST, Zero Window; 캡처 표본 표시 |
| HTTP | 20% | 상태 코드, TTFB, Total, Connect, TLS |

도달성·전송 품질(Local/Internet/TCP)에 합계 65%, DNS에 15%, 사용자 요청 결과(HTTP)에 20%를 배정합니다. 가중치 합은 1.0이고 각 값은 양수여야 합니다. 독립적인 물리 고장 확률이나 통계 학습 가중치는 아닙니다.

- 영역은 100점에서 시작합니다. 첫 주요 감점 경계는 기존 Rule과 맞춥니다(Gateway RTT>20ms, Internet RTT>150ms, Loss≥3%, DNS>300ms, TCP≥5%, TTFB>800ms). TCP 1~5% 재전송은 정상 점수 범위 내 소폭 감점입니다. 모든 구간별 감점 수치는 [health_score.yaml](backend/app/health_score.yaml)을 참고하세요.
- DNS 서버별 지연, HTTP의 겹치는 시간 지표, TCP 재전송·중복 ACK는 각각 같은 그룹의 **최대 감점 1개**만 적용합니다. 나머지 독립 그룹을 합하되 0점에서 제한하고 실제 적용 감점을 저장합니다. `100−감점 합계=영역 점수`가 항상 성립합니다.
- 각 감점은 `code`, 원본 `metric`, 실제 `value`, `unit`, `threshold`, `operator`, 적용 `points`, 상한 적용 전 `assessed_points`, `reason`, `group`을 제공합니다. `top_causes.weighted_points`는 전체 점수에 반영된 감점입니다. 감점 원인이 물리적 장애 위치의 확정은 아닙니다.
- `null`, 비유한 수, 음수, 설정 유효 범위 위반은 제외합니다. 유효 성능 지표가 없는 영역은 `score=null`, `available=false`입니다. Capture 0개도 TCP 점수를 계산하지 않습니다. `coverage`는 영역의 설정 지표 중 유효 비율, `quality`는 complete/partial/unavailable입니다. TCP 표본 50개 미만 또는 미확인은 low_sample으로 표시하며 그 자체로 감점하지 않습니다.
- Cloudflare 직접 질의 실패만으로 DNS 전체를 감점하지 않습니다. 성공한 resolver 시간으로 점수를 계산하되 결측·collector partial을 표시합니다. System DNS가 없으면 클라이언트의 DNS 품질이 검증됐다고 해석하지 않습니다. 저장된 실제 0ms는 그대로 유지합니다.
- Overall은 유효 영역만 가중치를 정규화한 평균이며, 유효 영역의 원래 가중치 합이 0.50 이상이어야 제공됩니다. Overall coverage는 누락 영역을 포함한 원래 가중치로 계산합니다. 부분 데이터에서 높은 점수가 나와도 coverage/quality를 함께 읽어야 합니다.
- v1에 없는 Link/Interface 상태는 추측하지 않습니다. Traceroute timeout/hop 수만으로 감점하지 않습니다. HTTP 수집 실패로 측정값이 없으면 원격 서버 장애를 단정하지 않고 계산 불가/부분 측정으로 처리합니다. HTTP 4xx/5xx가 실제 저장된 경우는 상태 코드 감점을 적용합니다. 높은 TTFB에는 네트워크와 서버 처리 요인이 섞입니다. RST는 정상 연결 종료에서도 관측될 수 있습니다.

`health_scores` 테이블은 `(measurement_id, score_version)`별 불변 결과, 전체/영역 점수, 감점, YAML snapshot/hash, 생성 시각을 저장합니다. 정책 변경 시 `score_version`을 바꾸고 Backend를 재빌드하세요. 동일 버전으로 YAML을 변경해 기존 결과를 덮어쓰는 작업은 거부합니다. 기존 버전 결과는 남고 새 버전 Backfill 결과가 별도로 추가됩니다.

API: `GET /api/v1/measurements/{id}/health-score`는 동일한 `X-NetDoctor-Key` 인증을 사용합니다. 기존 Measurement/Diagnosis의 Measurement 객체와 History에 optional `health_score`가 추가됩니다. 미계산 Measurement의 필드는 null이고 별도 점수 API는 404입니다. GET 요청은 점수를 새로 저장하지 않습니다. 신규 업로드는 Rule과 Score를 AI 호출 전에 저장하며 Ollama 장애 시에도 둘 다 제공합니다.

기존 실험 Backfill은 기본 dry-run입니다. 범위와 Agent를 확인한 후 신규 Score만 INSERT하고 기존 Measurement/Rule/AI는 수정하지 않습니다.

```bash
docker compose build backend frontend
docker compose up -d --no-deps backend frontend
docker compose exec -T backend python -m app.tools.backfill_health_scores --dry-run
docker compose exec -T backend python -m app.tools.backfill_health_scores --apply
```

프로젝트 루트에서 CSV까지 생성하려면 환경의 `DATABASE_URL`을 설정한 Python으로 `PYTHONPATH=backend python -m app.tools.backfill_health_scores --apply --csv reports/health_score_experiment.csv`를 실행합니다. DB URL의 비밀번호를 출력하거나 셸 이력에 직접 적지 마세요. 이미 계산한 범위의 재실행은 0건 INSERT입니다. 기본 범위는 실제 Agent ID의 21~40입니다. `reports/health_score_summary.csv`(조건 평균), `reports/health_score_representatives.csv`(22/26/31/36)도 함께 생성됩니다. 조건 이름은 사용자 제공 실험 mapping으로 CSV에만 붙이며 Measurement에 새 label을 기록하지 않습니다.

Dashboard 개요/측정 상세에서 영역 카드를 클릭하면 점수→감점→원본 필드/값/경계까지 확인할 수 있습니다. 기존 Rule 경보와 AI 진단은 유지하고, History와 최근 측정 표는 DB에 저장된 점수만 표시합니다. 신규 AI 요청에는 읽기 전용 점수 근거를 제공하며 기존 AI 결과는 다시 생성하지 않습니다.

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
