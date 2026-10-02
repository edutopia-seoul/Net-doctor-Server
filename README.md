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
- `GET /api/v1/diagnoses`, `GET /api/v1/diagnoses/{id}`
- `GET /api/v1/agents/{agent_id}/history`
- Swagger: `http://127.0.0.1:8000/docs`

## Dashboard

`http://127.0.0.1:3001`에서 한글 대시보드의 개요, 측정 상세, AI 진단, 이력 탭을 확인합니다. 외부 Caddy 경로는 `https://ikeawolf.duckdns.org:51739/NetDoctorServer/`입니다(Caddy 인증 필요). 화면의 API 키 입력란에 `.env`의 `AGENT_API_KEY`를 입력합니다. 키는 브라우저 탭의 sessionStorage에만 보관하며 JavaScript 번들에는 포함하지 않습니다. 과거에 저장된 AI 자유 서술은 영문으로 남을 수 있으나, 새 AI 진단은 한글로 요청합니다.

Frontend는 React/Vite와 Bklit Line/Area Chart, Tailwind CSS로 구성됩니다. 실제 Agent의 마지막 측정을 기준으로 종합 Rule 상태와 Gateway/Internet RTT, 손실률, System DNS, HTTP TTFB, TCP 재전송률을 표시합니다. 최근 20/50/100건의 시간순 이력, 측정 상세, 사실·규칙·AI 가설·권장 조치 분리, 밝은/어두운 테마를 제공합니다. 결측값은 0으로 대체하지 않습니다. Backend에 health score와 실험 label 필드가 없어 점수/label을 임의 생성하지 않습니다. Agent 상태는 heartbeat가 아니라 마지막 수신 시각으로 표시합니다.

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
