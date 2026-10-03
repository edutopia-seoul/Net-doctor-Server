# NetDoctor Server 개발 보고서

초기 작성: 2026-09-28 · 최종 갱신/검증: 2026-10-04 (Asia/Seoul). 초기 자동화 테스트의 Fixture와19~24절의 실제 Agent 데이터를 구별한다. v2/v2.1 점수 검증은 실제 Measurement ID21~40만 사용했다. v2.1 정책과 운영 배포 검증은24절, 기존 Bklit 개편 기록은25절에 보존한다.

## 1. 담당 역할

별도 Ubuntu Agent가 전송하는 Measurement JSON을 인증·검증·저장하고, Rule Engine을 먼저 실행한 뒤 Ollama AI 분석을 저장한다. 조회 API와 React Dashboard를 제공한다.

## 2. 초기 시스템 환경

| 항목 | 조사 결과 |
| --- | --- |
| OS | Ubuntu 26.04.1 LTS. 지시서의 24.04와 실제 설치 버전이 다름 |
| CPU / RAM | Intel Core i7-9700 8 cores / 15 GiB, swap 4 GiB |
| GPU | GeForce GTX 1650. `nvidia-smi`는 NVML driver/library mismatch로 실패 |
| Docker / Compose | Docker 29.1.3 / Compose 2.40.3 |
| 언어 도구 | Host Python 3.14.4, backend image Python 3.12, Node.js 22.22.1 |
| 기존 포트 | 3000은 LivLab UI가 사용. 8000·3001·5432는 초기 미사용 |
| 기존 Container | LivLab, KBAI, Minecraft 관련 Container가 실행 중. 변경하지 않음 |
| PostgreSQL / Ollama | Host PostgreSQL 없음. Host Ollama 서비스 실행 중 |
| 네트워크 | 서버 사설 IP `192.168.0.201`; Ollama는 이 IP의 11434번에 바인딩 |

## 3. 설치한 소프트웨어

| 이름·버전 | 목적 |
| --- | --- |
| PostgreSQL 16.14 (Docker) | Agent·Measurement·Diagnosis 영속 저장 |
| FastAPI 0.116.1 / SQLAlchemy 2.0.43 / Pydantic 2.x | API·DB·입력/AI 출력 검증 |
| React 19.3.0 / Vite 8.3.1 / Nginx 1.31.6 | Dashboard 빌드와 HTTP 제공 |
| Ollama client 0.32.1 (기존 Host) / `qwen3.5:4b-q4_K_M` | 로컬 AI 분석 |

Ollama는 기존 Host 설치를 재사용한다. GPU 드라이버 문제와 기존 서비스 상태를 고려해 새 Ollama Container는 만들지 않았다.

## 4. 구현 구조

```text
Ubuntu Agent --REST + X-NetDoctor-Key--> FastAPI :8000
                                          |--> PostgreSQL 16 (host 127.0.0.1:5432)
                                          |--> YAML Rule Engine
                                          |--> Host Ollama :11434
React/Nginx :3001 --/api proxy----------> FastAPI
```

Backend와 Frontend Container는 이 호스트에서 Ollama 및 서로에 접근할 수 있도록 host network를 사용한다. PostgreSQL만 Docker bridge에 두고 `127.0.0.1:5432`로 제한했다.

## 5. 생성/수정한 주요 파일

- `docker-compose.yml`: PostgreSQL·Backend·Frontend와 영속 volume.
- `.env.example`, `.env`, `.gitignore`: 설정 예시, 실제 비밀값, Git 제외 규칙.
- `backend/app/main.py`: 등록·측정·진단·이력 API와 AI fallback.
- `backend/app/schemas.py`: Agent/Measurement 요청과 조회 응답 schema.
- `backend/app/models.py`, `db.py`: SQLAlchemy Table과 DB 연결.
- `backend/app/rule_engine.py`, `rules.yaml`: 다중 규칙, threshold, evidence.
- `backend/app/ai.py`: Ollama 호출, JSON/Pydantic 검증, 서버 측 measured facts 고정.
- `frontend/src/main.jsx`, `styles.css`: 4개 Dashboard 화면.
- `backend/tests/`: API·Rule 자동 테스트와 6개 Measurement fixture.

## 6. 실행한 주요 명령어

```bash
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health
PYTHONPATH=backend .venv/bin/pytest -q backend/tests
npm --prefix frontend run build
docker compose restart postgres
```

새 설치 시 `.env.example`을 `.env`로 복사하고 PostgreSQL 비밀번호와 Agent API key를 고유한 무작위 값으로 바꾼다. 현재 배포에는 이미 무작위 값이 설정돼 있으며 보고서에는 기록하지 않는다.

## 7. 설정 변경 사항

작업 위치는 기존 빈 저장소 `/home/ikeawolf/net-proj-server/NetDoctor-Server`다. `/opt` 권한 변경 없이 프로젝트를 격리했다. Caddy, 기존 Docker 서비스, 방화벽, 공유기 설정은 변경하지 않았다. 3000 충돌을 피해 Dashboard는 3001을 사용한다. 기존 호스트 Ollama의 LAN 바인딩과 Docker bridge 연결 문제로 Backend/Frontend를 host network로 실행한다. PostgreSQL은 외부에 공개하지 않는다.

## 8. Database 구조

| Table | 내용 |
| --- | --- |
| `agents` | 안정적 agent_id, hostname, 버전, 최근 수신, interface/capability metadata |
| `measurements` | 수집 시각, target/network, metrics, collector status |
| `rule_diagnoses` | measurement별 severity, 발동 규칙, 근거 값 |
| `ai_diagnoses` | AI 사용 가능 여부, 원인, confidence, 사실·규칙·가설·권고, model |

JSON 필드는 PostgreSQL JSONB이며 `postgres_data` Docker volume에 영속화된다.

## 9. Rule Engine

| Rule | 기준 (`rules.yaml`) |
| --- | --- |
| GATEWAY_UNREACHABLE / INTERNET_UNREACHABLE | 해당 ping loss 100% |
| LOCAL_PACKET_LOSS / EXTERNAL_PACKET_LOSS | 해당 ping loss 3% 이상 |
| LOCAL_HIGH_LATENCY / EXTERNAL_HIGH_LATENCY | gateway RTT 20 ms 초과 / internet RTT 150 ms 초과 |
| DNS_DELAY | DNS 응답 300 ms 초과 |
| TCP_RETRANSMISSION_HIGH | 재전송률 5% 이상 |
| HTTP_SERVER_RESPONSE_DELAY | TTFB 800 ms 초과 |
| INSUFFICIENT_DATA | 사용 가능한 주요 측정값이 없음 |

여러 규칙을 동시에 발동할 수 있다. 각 finding에 판단에 사용한 실제 수치를 기록한다.

## 10. AI 구성

- 모델: Host Ollama의 `qwen3.5:4b-q4_K_M`.
- 입력: 현재 구조화 Measurement, Rule Engine 결과, 최근 최대 4개 이전 측정의 주요 metrics.
- Prompt: 측정값 발명 금지, 사실·Rule finding·가설 구분, 근거 부족 시 추가 측정 요구. 사용자용 서술은 한글로 요청하고 JSON 키·enum·측정 수치는 변경하지 않는다. 실제 통합에서 traceroute timeout 오인과 출력 잘림이 발견되어 AI 입력은 hop 배열을 제외한 요약으로 줄이고, 서술의 숫자·IP 오인과 DNS 지연 오판을 금지했다.
- 출력: JSON format + Pydantic schema. Severity는 normal/warning/critical, confidence는 LOW/MEDIUM/HIGH만 허용.
- Qwen의 thinking 지연을 줄이기 위해 `think=false`, `num_predict=320`, timeout 120초 사용.
- 모델이 보낸 `measured_facts`와 `rule_findings`는 저장 직전 서버가 실제 Measurement와 Rule 결과로 덮어쓴다. `primary_cause`도 발동 규칙을 근거로 한 관측 문제로 고정한다. AI 가설은 별도 필드에만 표시하고, 무의미한 목록 항목과 숫자가 들어간 AI 자유 서술 항목은 제외한다.
- AI 연결·시간 초과·잘못된 JSON이 발생해도 Rule Diagnosis를 유지하고 `available=false`를 저장한다.

## 11. API

| Method | Endpoint | 역할 |
| --- | --- | --- |
| GET | `/health` | 서비스 상태 |
| POST | `/api/v1/agents/register` | Agent 등록/갱신 |
| GET | `/api/v1/agents`, `/api/v1/agents/{agent_id}` | Agent 조회 |
| POST | `/api/v1/measurements` | Measurement 저장 → Rule → AI |
| GET | `/api/v1/measurements`, `/api/v1/measurements/{id}` | 측정 조회 |
| GET | `/api/v1/diagnoses`, `/api/v1/diagnoses/{id}` | 진단 조회 |
| GET | `/api/v1/agents/{agent_id}/history` | Agent 시간별 이력 |

`/api/v1/*`에는 `X-NetDoctor-Key`가 필요하다. Swagger는 `/docs`.

## 12. Dashboard

React 한글 탭 4개: 개요(Agent 온라인/오프라인·최신 심각도·주요 지표·최근 진단), 측정 상세(측정값·수집기 상태·규칙 근거), AI 진단(관측 문제·심각도·신뢰도·사실·규칙·가설·영향·권고·추가 확인), 이력(RTT·손실률·DNS·TCP 재전송·HTTP 첫 응답 그래프). 사실과 가설은 다른 제목/영역에 표시한다. API 키는 화면에서 입력하며 JS bundle에 포함하지 않는다. 기존 영문 규칙 코드/근거와 주요 수집기 상태는 화면에서 한글로 표시한다. 새 AI 서술은 프롬프트에서 한글을 요청하며 기존 저장된 AI 자유 서술은 자동 번역하지 않는다. 외부 Caddy 경로는 사용자가 설정한 `https://ikeawolf.duckdns.org:51739/NetDoctorServer/`이다. Caddy 설정은 이 작업에서 변경하지 않았다.

## 13. 테스트

| 목적 | 입력 | 예상 결과 | 실제 결과 |
| --- | --- | --- | --- |
| 인증 | Header 없음/틀린 값 | 401 | 401, 성공 |
| Agent 등록 | demo-agent 정보 | 200 및 저장 | 200, 성공 |
| 정상 측정 | `normal.json` | 저장, Rule 정상 | 성공 |
| 일부 null/Collector 실패 | `gateway_failure.json` | 저장 및 gateway 장애 | 성공 |
| 잘못된 schema | version 2.0 | 422 | 422, 성공 |
| Rule 10종/다중 발동 | 각 fixture와 threshold 입력 | 규칙·근거 일치 | pytest 성공 |
| AI 정상 응답 | Ollama + `dns_delay.json` | 구조화 결과 저장 | measurement #9, `available=true`, MEDIUM |
| AI 근거 고정 | 가짜 measured fact를 내는 mock | 서버가 실제 값으로 교체 | pytest 성공 |
| 한글 AI 응답 | 실제 Ollama + `normal.json` | 구조화된 한글 진단 | `available=true`, 주요 원인 한글, 성공 |
| 정상 결과의 null 서술 | `primary_cause=null`, `impact=null` mock | 한글 기본 문구로 구조화 결과 유지 | pytest 성공 |
| AI 장애 | 연결 거절/timeout 및 mock | Rule 유지, `available=false` | 성공 |
| PostgreSQL 영속성 | Container restart 후 #9 조회 | 기존 데이터 유지 | 200, 성공 |
| DB 백업 | `pg_dump` 출력 스트림 | SQL dump 생성 가능 | 20,307 bytes, 성공 |
| 공개 UI 경계 | Frontend 3001 / API proxy | 200 / 인증 401 | 성공 |
| 한글 UI 배포 | 로컬 HTML/JS 및 외부 Caddy 경로 | 한글 번들 제공, 인증 유지 | 로컬 200·한글 문자열 확인, 외부 무인증 401 |

`PYTHONPATH=backend .venv/bin/pytest -q backend/tests`: **15 passed**. Frontend `npm run build`: 성공. Swagger `/docs`: HTTP 200. 한글 UI는 로컬 정적 자산으로 검증했고, 외부 경로는 Caddy 인증 때문에 무인증 응답 401까지 확인했다. 실제 Agent 최초 통합은 21절, 최종 4종 실험은 22절에 기록했다. 인증 후 브라우저 시각 캡처는 아직 수행하지 않았다.

## 14. 발생한 문제와 해결 과정

1. 초기 local SQLite 검증에서 JSON dict 저장 오류가 발생했다. SQLAlchemy JSON 타입에 PostgreSQL JSONB variant를 적용했다.
2. 초기 Frontend `build` 명령이 개발 서버를 실행했다. `vite build`로 수정했다.
3. 검증용 Uvicorn이 8000 포트를 점유해 첫 Compose 기동이 실패했다. 검증 프로세스 종료 후 재기동했다.
4. Container 내부 Rule 파일 경로가 달라 500이 발생했다. 모듈 위치 기준으로 설정 파일을 찾도록 수정했다.
5. Docker bridge에서 Host Ollama 연결이 timeout이었고 Frontend reverse proxy도 실패했다. Backend/Frontend host network로 조정해 둘 다 200 확인했다.
6. Qwen thinking으로 90초 timeout, 낮은 출력 제한으로 JSON 잘림, 일부 응답의 타입 불일치가 발생했다. thinking 비활성화·출력 길이 조정·문자열 정규화로 실제 AI 저장에 성공했다.
7. 초기 Dashboard key가 JS build에 포함되는 문제가 있었다. 키 입력 방식으로 바꾸고 기존 테스트 DB 비밀번호를 갱신했다. `.env` 권한은 600이다.
8. 한글 AI 요청의 정상 측정 결과에서 Ollama가 `primary_cause`와 `impact`를 `null`로 반환해 Pydantic 검증이 실패했다. 비어 있는 서술에 한글 기본 문구를 적용하고 회귀 테스트를 추가했다. 이후 실제 Ollama에서 한글 구조화 응답을 확인했다.

## 15. 최종 동작 상태

완성: Compose 3서비스 실행, FastAPI health/Swagger, PostgreSQL 저장·재시작 후 유지, Agent/Measurement API, Rule Engine, 실제 Ollama AI, AI fallback, 한글 4개 Dashboard 화면, History API/차트, README/테스트/보고서.

부분 확인: 실제 Agent의 초기 11건(21절)에 이어 4종 실험 20건(ID 21~40)의 DB·Rule·AI·History와 Dashboard 데이터 공급을 검증했다(22절). Dashboard 정적 자산과 API proxy는 HTTP 경계에서 검증했으나 Caddy 인증 후 실제 브라우저 시각 캡처는 미실시. AI 실측 사실은 정확하지만 자유 서술 일부는 근거가 약해 발표 시 한계로 설명한다. 오래된 테스트 Agent의 AI 서술은 영문으로 남을 수 있고 Ollama 동시 요청 과부하 방지는 아직 구현하지 않았다.

미구현: 별도 Ollama Container는 의도적으로 생략하고 기존 Host Ollama를 사용한다.

## 16. 남은 작업

실제 Agent 연결과 Normal/Latency/Loss/Mixed 4종 실험은 완료했다(21~22절). 다음은 발표 전 Dashboard의 인증 후 실제 브라우저 캡처, Agent 측 원시 DNS `0 ms` parser 근거 확인, AI 자유 서술의 근거 부족 사례를 발표에서 명시하는 일이다. LAN 밖에서 사용할 경우 API TLS/접근 제어를 별도 구성해야 한다.

## 17. 발표/PPT용 핵심 내용

- 서버는 Agent 실측 JSON을 저장한 후 규칙과 AI를 순서대로 실행한다.
- 기술: FastAPI, PostgreSQL JSONB, YAML Rule Engine, Ollama Qwen3.5 4B, React.
- Rule Engine은 threshold에 따라 재현 가능한 결과와 수치 근거를 낸다.
- AI는 측정·규칙·이력을 종합해 가설과 해결 권고를 작성한다. 측정 사실은 서버가 원본 값으로 고정한다.
- 대표 시연: 최종 4종 실험 #22(정상), #26(지연), #31(손실), #36(혼합)의 실측값→Rule→AI 흐름. 지연 조건 Internet RTT는 정상 2.827 ms에서 203.120 ms로, 손실 조건 TCP 재전송률은 0%에서 4.292%로 증가했다. AI 장애에도 Rule 결과가 남는다.
- 화면: Overview → Measurement Detail → AI Diagnosis → History.

## 18. 발표용 캡처 목록

1. `docker compose ps` (PostgreSQL healthy 포함)
2. Swagger `/docs`
3. Dashboard Overview
4. Measurement Detail의 수치·Collector 상태·Rule evidence
5. AI Diagnosis의 measured facts/rule findings/hypotheses 구분
6. History 5개 지표 차트
7. DB 저장된 실제 Agent 실험 #22·26·31·36과 AI 결과
8. Ollama 장애 fallback 결과

## 19. 실제 Agent 통합 테스트

이 절은 전송 전 기준치와 대기 상태의 당시 기록이다. 실제 최초 수신 결과는 21절, 최종 4종 장애 실험은 22절에 정리했다.

- 시작 시각: 2026-09-28 17:02 KST. 실제 Agent 전송 대기 중.
- 수신 전 기준치: 기존 테스트용 Agent 2개(`compose-agent`, `demo-agent`), Measurement 8건(최대 ID 9), Rule Diagnosis 8건, AI Diagnosis 8건. 아래 통합 결과에는 이 기록을 포함하지 않는다.
- LAN 접근: `http://192.168.0.201:8000/health` HTTP 200. 등록·측정 API는 키 없는 POST에 401, 인증된 빈 POST에 schema 422로 응답(데이터 저장 없음). Backend는 8000에서 수신하며 PostgreSQL 5432는 `127.0.0.1`에만 바인딩.
- API 키: 프로젝트 루트 `.env`에 설정됨(값 미기록), 파일 권한 600. Agent는 `X-NetDoctor-Key` 헤더 사용.
- Agent ID/등록 정보: 미수신.
- 실제 수신 Measurement 개수: 0건(대기 중). Pending 9건과 신규 측정 1건은 아직 구분·검증 전.
- PostgreSQL 저장 결과: 실제 Agent 기록 미수신.
- Rule Engine / AI 처리 결과: 실제 Agent 기록 미수신.
- Dashboard / History: `http://192.168.0.201:3001/api/v1/agents` 및 `/diagnoses`가 인증된 요청에 HTTP 200으로 응답. 실제 Agent 기록 표시 여부는 미검증.
- Schema/API 문제 및 수정 사항: 실제 전송 전이라 확인된 문제 없음. 서버 코드·네트워크 설정 변경 없음.
- 통합 최종 성공 여부: 미완료(17:06 KST까지 실제 Agent 전송 없음). `iperf3`는 현재 Host에 설치되지 않았고 5201 포트도 열려 있지 않아 2차 실험으로 보류.

## 20. LAN TCP 접근 장애 분석

- 증상: Agent `192.168.0.202`에서 서버 `192.168.0.201` ping 3/3 성공, HTTP TCP 8000·3001은 최초 timeout(Agent 측 보고).
- 서버 주소/라우팅: `enp6s0`에 `192.168.0.201/24`, `192.168.0.202`까지 같은 인터페이스의 직접 경로. 기본 게이트웨이 `192.168.0.1`.
- Listen: `ss -lntp`에서 Backend `0.0.0.0:8000`, Frontend `0.0.0.0:3001`. Uvicorn은 `--host 0.0.0.0`; Nginx는 `listen 3001`.
- Docker: Backend/Frontend는 `network_mode: host`라 별도 Docker Port Publish 항목이 없는 것이 정상. PostgreSQL만 `127.0.0.1:5432->5432/tcp`.
- 서버 자체 테스트: `127.0.0.1:8000/health` HTTP 200, `192.168.0.201:8000/health` HTTP 200, `127.0.0.1:3001/` 및 `192.168.0.201:3001/` HEAD HTTP 200. 네 경우 모두 TCP 연결 성공.
- 방화벽 최초 상태: UFW active, incoming 기본 deny. 8000·3001 허용 규칙은 없었음. nftables의 INPUT 정책도 drop. 이것이 Agent의 TCP timeout 원인으로 확인됨.
- 수정: 기존 `/etc/ufw/user.rules`를 `/etc/ufw/user.rules.netdoctor-2026-09-28.bak`에 백업. `enp6s0`에서 출발지 `192.168.0.202`, 목적지 `192.168.0.201`에 한해 TCP 8000·3001을 허용하는 UFW 규칙 2개 추가. 잠시 사용한 `/24` 허용 규칙은 단일 Agent IP 확인 후 삭제. UFW 전체 비활성화, Docker/애플리케이션 변경, 포트 포워딩은 하지 않음.
- 패킷 관찰: 수정 직후 20초 `tcpdump`에서 Agent 재시도가 없어 0패킷. 이후 nftables 8000 허용 카운터가 3 증가하고 Backend 로그에 `192.168.0.202`의 `GET /health`와 `GET /openapi.json` HTTP 200이 남아 실제 Agent→Server TCP/HTTP 통신을 확인. 3001 허용 카운터는 아직 0으로 Agent 재시도 기록 없음.
- 최종 결과(2026-09-28 17:17 KST): Agent의 Backend 8000 접근은 해결 확인. 이후 3001 허용 카운터에 Agent SYN 1건도 확인했으나 Agent의 HTTP 응답/브라우저 화면은 별도 확인 필요. PostgreSQL 5432·Ollama 11434 규칙과 기존 서비스는 변경하지 않음.

## 21. 실제 Agent End-to-End 통합 검증

- 검증 시각: 2026-09-28 18:27 KST. 실제 Agent ID `549dc09b-4438-4e02-ad3b-2e70c4110b95`만 대상으로 집계했다. 기존 `compose-agent`, `demo-agent`와 테스트 Measurement 8건은 제외했다.
- Agent 등록: hostname `IKEAWOLF-SERVER-C`, OS `Ubuntu 26.04.1 LTS`, 버전 `0.1.0`, 인터페이스 `wlp1s0`(`192.168.0.202`, 보고 링크 속도 527 Mbps), capabilities `ping, traceroute, dns, http, tshark, iperf3, ethtool`. `last_seen`은 2026-09-28 17:51:51 KST. 등록 200 확인; 로그에 등록 422가 1회 있었으나 이후 정상 등록됐고 해당 요청 본문은 보관되지 않아 원인을 단정할 수 없다.
- 수신 수: 실제 Agent Measurement **11건**, DB ID 10~20. 기존 Pending 9건(ID 10~18) + 신규 수동 Measurement 1건 + systemd Measurement 1건(ID 19~20)이다. 따라서 예상보다 1건 많았던 이유는 추가 자동 측정이며 중복 저장이 아니다. DB에는 수동/systemd 출처 필드가 없어 ID 19·20 각각의 실행 방식을 DB만으로 독립 판별하지는 못한다.
- PostgreSQL 저장: 11건 모두 올바른 agent_id로 연결됐고 `timestamp`, `network`, `metrics`, `collector_status`가 저장됐다. Rule Diagnosis 11건, AI Diagnosis 11건. 실제 Agent의 Measurement schema 저장 실패는 확인되지 않았다. Agent 측 개별 POST 응답 기록이 없어 11개 요청 각각의 HTTP 200 수신 여부는 별도 확인 필요.
- 최신 정상 측정: ID 20, Agent timestamp 2026-09-28 17:54:04 KST. 게이트웨이 평균 RTT **2.467 ms**, 손실 **0%**; 인터넷 평균 RTT **15.361 ms**, 손실 **0%**; 시스템 DNS **0 ms**, Google DNS **64 ms**, Cloudflare DNS null(collector `partial`); traceroute는 12개 probe 기록, 첫 홉 외 다수 timeout이며 latency jump 없음; HTTP TTFB **169.541 ms**, 상태 **200**; TCP 재전송률 **0%**. `iperf3`는 미설정으로 `skipped`. 값은 DB의 Agent 전송 JSON과 API 응답에서 일치한다. Agent 컴퓨터의 별도 원본 출력과 독립 대조는 미완료.
- Rule Engine: 실제 11건을 현재 YAML threshold로 재계산해 DB 결과와 **11/11 일치**. 정상 7건, 주의 4건. ID 11·15는 게이트웨이/인터넷 지연, ID 13은 패킷 손실+게이트웨이 지연, ID 16은 패킷 손실+HTTP 첫 응답 지연. 최신 ID 20은 `severity=normal`, `triggered_rules=[]`, `findings=[]`로 정상 상태 오탐 없음. Threshold는 변경하지 않았다.
- AI Diagnosis: 모델 `qwen3.5:4b-q4_K_M`. 최초 일괄 전송에서는 1/11건만 성공하고 6건은 120초 ReadTimeout, 4건은 320토큰 제한 부근의 JSONDecodeError로 Rule fallback됐다. Host Ollama 추론은 약 6 tokens/s로 동시 요청에 취약했다. 프롬프트 출력을 축약하고 AI 입력의 개별 traceroute hop 배열을 제외해 단일 실제 측정의 구조화 응답 시간을 약 30~33초로 줄였다. 실패 건을 **순차 재분석**하고 과도한 기존 서술을 보정한 뒤 **11/11 `available=true`**, Rule/AI severity 불일치 0건. 최신 ID 20은 `normal`, `HIGH`, 주요 관측 문제는 “규칙 기준에서 뚜렷한 장애 징후가 확인되지 않았습니다.”, 영향은 “사용자 영향이 확인되지 않았습니다.”, 권고는 주기적 재측정이다.
- Hallucination 검사: 실제 11건의 `measured_facts`가 저장된 metrics에서만 생성됐음을 **11/11 정확 일치**로 확인했고, `rule_findings`도 Rule Engine 결과와 **11/11 일치**했다. 초기 AI는 traceroute timeout을 경로 고장으로 단정하고, DNS 조회 결과 IP를 DNS 서버 설정처럼 오인하거나 `null`·잘린 JSON 조각을 목록에 넣었다. Prompt를 강화하고 숫자/IP가 들어간 AI 자유 서술 목록과 무의미한 항목을 제거했다. `primary_cause`는 발동 규칙에 근거한 **관측 문제**로 서버에서 고정하며, 불확실한 원인은 `hypotheses`에만 둔다. 기존 실제 Agent의 문제 서술도 수정했다. 이는 AI 가설의 진실을 보증하지는 않으므로 발표에서 가설로 구분한다.
- History/API: 실제 Agent의 `/api/v1/agents/{agent_id}/history`가 11건을 timestamp 오름차순으로 반환하고 다른 Agent 데이터가 섞이지 않았다. 최신 두 건의 Agent timestamp는 서버 `created_at`보다 약 **133초 앞서** 있어 Agent·Server 시계 동기화가 필요하다.
- Dashboard: Frontend `3001`과 `/api/v1/agents`, `/diagnoses`, 실제 Agent history, ID 20 상세는 모두 HTTP 200. 현재 API 정렬에서 실제 Agent가 첫 번째이고 최신 진단은 ID 20이라 개요·측정 상세·AI 진단·이력(11개 점)에 실제 값이 공급된다. `Measured Facts`/`Rule Findings`/`AI Hypotheses`/`Recommendations` 영역은 분리돼 있다. Collector의 `partial`·`skipped`도 한글로 표시한다. 실제 브라우저 시각 캡처는 미실시. 현재 마지막 수신 후 5분이 지나 `offline` 표시이며 발표용 `online` 캡처는 새 Agent 측정 직후 수행해야 한다.
- Schema/API 문제: Measurement 11건은 현재 `schema_version=1.0` 계약으로 저장됐고 중복 저장은 없다. 예상 대비 1건 추가 수신은 systemd Measurement로 설명된다. 등록 422 1회 원인과 Agent 측 각 HTTP 응답은 Agent 로그 확인이 남았다.
- 후속 Normal/Latency/Loss/Mixed: 같은 Agent의 네 실험을 별도 timestamp로 저장·규칙 판정·History 조회할 준비는 됐다. 다만 현재 AI는 동기식이므로 **각 POST 완료 후 다음 측정 전송**이 필요하며, 동시에 여러 건을 밀어 넣으면 Ollama timeout/fallback이 재발할 수 있다. 시나리오 자동 라벨링·4종 비교 화면은 아직 구현하지 않았고 이번 단계에서 추가하지 않았다.
- 최종 판정: 실제 Agent의 수집→API→PostgreSQL→Rule→Ollama→AI→History→Dashboard 데이터 공급은 **성공**. 최초 동시 일괄 전송의 자동 AI 처리와 Agent 측 개별 HTTP 응답/브라우저 시각 검증은 **부분 확인**이며, 순차 전송 및 발표 전 실화면 확인이 필요하다.

## 22. 최종 4종 네트워크 장애 실험

### 22.1 실험 설계

- Server: `IKEAWOLF-SERVER-B` (`192.168.0.201`), Agent: `IKEAWOLF-SERVER-C` (`192.168.0.202`, `wlp1s0`), Agent ID `549dc09b-4438-4e02-ad3b-2e70c4110b95`.
- NORMAL(netem 없음), HIGH_LATENCY(`delay 200 ms`), PACKET_LOSS(`loss 10%`), MIXED(`delay 100 ms + loss 5%`)를 각 5회 측정했다. 설정 장애(configured fault)와 관측 지표(observed evidence)는 별개로 평가한다.
- netem은 Agent `wlp1s0` 전체에 적용됐다. 게이트웨이로 향하는 패킷도 영향을 받으므로 높은 Gateway RTT는 장비 자체 고장의 증명이 아니다. Rule 코드의 `LOCAL_*`/`EXTERNAL_*`은 각각 Gateway/Internet 측정 방향을 가리키며 실제 고장 위치의 확정이 아니다. `HTTP_SERVER_RESPONSE_DELAY`도 높은 HTTP TTFB를 뜻할 뿐 서버 처리 시간만 분리한 진단은 아니다.

### 22.2 분석 대상

- DB ID **21~40만** 사용했다. NORMAL 21~25, HIGH_LATENCY 26~30, PACKET_LOSS 31~35, MIXED 36~40. 기존 개발·Pending·systemd 데이터는 통계에서 제외했다.
- Agent가 제공한 참고 평균과 DB 재계산값은 소수 셋째 자리까지 일치한다. 별도의 Agent 원본 보고서 파일은 Server에서 읽지 않았으므로 이 비교는 **사용자가 제공한 참고값과 DB값의 대조**다.
- 재현: 프로젝트 루트에서 `python3 reports/analyze_final_experiment.py`. 이 스크립트는 PostgreSQL을 SELECT만 하고 원본 Measurement·Rule·AI·Threshold를 수정하지 않는다.

### 22.3 시간 동기화

- 확인 시각: **2026-09-28 21:51 KST**. Server `timedatectl status`: `System clock synchronized: yes`, `NTP service: active`, Asia/Seoul. `chronyc tracking`: `Leap status: Normal`, 시스템 시간 오프셋 약 **+0.000061초**.
- Agent의 실험 전후 동기화 정상은 Agent 측 보고에 근거하며, 이 서버에서 Agent의 현재 시계를 직접 재검사하지 않았다.
- ID 21~40의 Agent 측정 시각은 2026-09-28 **19:32:17~19:56:29 KST**. 각 DB `created_at - timestamp`는 **24.496~29.790초**(평균 26.524초)로 모두 양수다. 수집·전송·진단 사이 지연을 포함하므로 시계 오차 자체로 단정하지 않는다. ID 21~40은 timestamp가 서로 다르고 순서가 증가한다.

### 22.4 데이터 무결성

- ID 21~40 **정확히 20건**, Agent ID 20/20 일치, 고유 timestamp 20개, timestamp+network+metrics+collector_status 기준 완전 중복 **0건**. `network`, `metrics`, `collector_status`, Rule Diagnosis, AI Diagnosis가 각각 **20/20** 존재한다.
- HTTP 상태는 20/20 `200`. Cloudflare 직접 DNS 시간은 20/20 `null`, DNS Collector는 20/20 `partial`; iperf3는 20/20 `skipped`. 실패한 DNS 시간을 0으로 바꾸지 않았다.
- LOSS-03(#33)의 System DNS는 `null`이고 LOSS-04(#34)의 Google DNS도 `null`이다. 따라서 PACKET_LOSS의 System/Google DNS 유효 표본은 각각 **n=4**, Cloudflare는 전 조건 **n=0**이다.
- 여러 System DNS 값은 실제 저장값 `0.0 ms`다. 원시 `dig` 출력이나 Agent parser 로그가 Server DB에 없어서 0의 발생 경위는 독립 검증하지 못했다. 값을 임의로 null·양수로 바꾸지 않았으며, 0 자체로 DNS가 완벽하다고 주장하지 않는다.

### 22.5 NORMAL

- Gateway RTT 평균 **3.388 ms**, Internet RTT **2.827 ms**, Internet Loss **0%**, HTTP TTFB **262.768 ms**, TCP 재전송률 **0%**. 5/5 Rule `normal`, 발동 코드 없음; AI도 5/5 `normal`, `HIGH` confidence.
- DNS partial은 존재하지만 성공한 DNS 시간에서 `DNS_DELAY` 증거는 없다. 이를 정상 네트워크 지표와 분리한다.

### 22.6 HIGH_LATENCY

- Gateway RTT **202.980 ms**, Internet RTT **203.120 ms**. NORMAL 대비 Internet RTT **+200.293 ms, 71.850배**. Internet Loss **0%**, TCP 재전송률 **0%**.
- HTTP TTFB **844.353 ms**: NORMAL 대비 **+581.585 ms, +221.33%, 3.213배**. 5/5 Rule `warning`, AI `warning`/`MEDIUM`.
- `EXTERNAL_HIGH_LATENCY` 및 `LOCAL_HIGH_LATENCY`가 각각 5/5, `HTTP_SERVER_RESPONSE_DELAY`는 4/5. 실제로 첫 Gateway hop부터 지연되어 인터페이스 전체 netem 적용과 양립한다. WAN 또는 원격 HTTP 서버 자체 고장으로 단정할 수 없다.

### 22.7 PACKET_LOSS

- Internet Loss **10.000%**(개별 **10, 20, 10, 10, 0%**), Gateway Loss 평균 **8.000%**. Internet RTT **4.082 ms**. TCP 재전송률 **4.292%**(개별 **8.333, 0, 3.333, 6.667, 3.125%**), NORMAL 대비 **+4.292%p**.
- HTTP TTFB **759.800 ms**: NORMAL 대비 **+497.031 ms, +189.15%, 2.892배**. 손실 실험의 TTFB 표본표준편차는 **870.517 ms**. LOSS-03(#33) **2280.194 ms**가 평균 기준 제곱편차 합계의 **76.26%**를 차지한다. 이 값은 실제 관측값이므로 제외하지 않았다. LOSS-02는 **204.828 ms**처럼 빠른 응답도 있었다.
- Rule은 4/5 `warning`, 1/5 `normal`; AI도 동일. LOSS-05(#35)는 이번 Ping에서 Gateway/Internet Loss가 모두 **0%**, TCP 재전송 **3.125% < 5%**이고 HTTP TTFB **260.206 ms**이므로 Rule 미발동은 해당 Measurement의 증거와 일치한다. 설정상 10% netem을 매 짧은 Ping 표본이 정확히 10%로 관측해야 하는 것은 아니다.

### 22.8 MIXED

- Gateway RTT **103.645 ms**, Internet RTT **103.736 ms**: NORMAL 대비 Internet RTT **+100.909 ms, 36.695배**. Internet Loss **8.000%**(**+8.000%p**), TCP 재전송률 **1.255%**(**+1.255%p**).
- HTTP TTFB **725.824 ms**: NORMAL 대비 **+463.056 ms, +176.22%, 2.762배**. 5/5 Rule `warning`, AI `warning`/`MEDIUM`.
- `LOCAL_HIGH_LATENCY` 5/5, `LOCAL_PACKET_LOSS` 3/5, `EXTERNAL_PACKET_LOSS` 3/5, `HTTP_SERVER_RESPONSE_DELAY` 2/5. 개별 손실·TCP 재전송은 모든 회차에서 동시에 나타나지 않았지만 집계에서 둘 다 증가했다.

### 22.9 통계 분석

모든 평균은 `null`을 제외한 산술평균, SD는 **표본표준편차(n−1)**다. 아래 형식은 **평균 ± SD [최소, 최대]; 유효 n**이다. 단위는 RTT/DNS/TTFB는 ms, 손실/재전송은 %다. 19개 원시 Metric 각각의 평균·표본 SD·최소·최대·유효 n은 [final_experiment_stats.csv](reports/final_experiment_stats.csv)에 있다.

| 조건 | Gateway RTT | Internet RTT | Internet Loss | System DNS | HTTP TTFB | TCP 재전송률 |
|---|---|---|---|---|---|---|
| NORMAL | 3.388 ± 1.370 [2.491, 5.633]; 5 | 2.827 ± 0.387 [2.463, 3.484]; 5 | 0.000 ± 0.000 [0, 0]; 5 | 25.400 ± 33.441 [1, 64]; 5 | 262.768 ± 60.118 [197.422, 330.416]; 5 | 0.000 ± 0.000 [0, 0]; 5 |
| HIGH_LATENCY | 202.980 ± 0.259 [202.700, 203.400]; 5 | 203.120 ± 0.363 [202.700, 203.500]; 5 | 0.000 ± 0.000 [0, 0]; 5 | 52.600 ± 117.617 [0, 263]; 5 | 844.353 ± 128.089 [734.644, 1066.528]; 5 | 0.000 ± 0.000 [0, 0]; 5 |
| PACKET_LOSS | 2.726 ± 0.513 [1.989, 3.422]; 5 | 4.082 ± 1.612 [3.192, 6.941]; 5 | 10.000 ± 7.071 [0, 20]; 5 | 15.250 ± 29.837 [0, 60]; **4** | 759.800 ± 870.517 [204.828, 2280.194]; 5 | 4.292 ± 3.266 [0, 8.333]; 5 |
| MIXED | 103.645 ± 1.221 [102.889, 105.778]; 5 | 103.736 ± 0.717 [102.800, 104.556]; 5 | 8.000 ± 8.367 [0, 20]; 5 | 33.000 ± 73.233 [0, 164]; 5 | 725.824 ± 277.367 [504.033, 1069.635]; 5 | 1.255 ± 1.745 [0, 3.571]; 5 |

해석: 지연만 가했을 때 RTT·HTTP TTFB는 함께 크게 늘었지만 TCP 재전송은 관측되지 않았다. 손실 조건에서는 Ping 손실과 일부 TCP 세그먼트 재전송이 관측되고 HTTP TTFB 변동이 커졌다. MIXED에서는 지연·손실·일부 재전송과 HTTP TTFB 증가가 함께 관측됐다. 이는 **이 실험의 상관관계**이며, TTFB 증가분을 RTT·DNS·서버 처리 시간으로 엄밀히 인과 분해한 결과는 아니다. 짧은 TShark 캡처(조건별 평균 약 30~33 패킷) 때문에 재전송률 표본 변동이 클 수 있다.

### 22.10 Rule Engine 평가

현재 `backend/app/rules.yaml` 기준 DB Rule 결과를 실제 저장 Metric으로 재계산한 결과 **20/20 정확히 일치**했다. Threshold는 변경하지 않았다. 아래 관측치의 G/I는 각각 Gateway/Internet의 **RTT/Packet Loss**, T는 HTTP TTFB, R은 TCP 재전송률이다. Evidence Consistent **YES**는 저장 Rule severity·코드·finding 숫자가 재계산 결과와 일치함을 뜻한다. 물리적 고장 위치까지 증명했다는 뜻은 아니다.

| Label (ID) | Observed Evidence: G; I; T; R | Severity | Triggered Rules | Evidence Consistent |
|---|---|---|---|---|
| NORMAL-01 (#21) | 5.633ms/0%; 2.794ms/0%; 330.416ms; 0% | normal | — | YES |
| NORMAL-02 (#22) | 2.512ms/0%; 2.682ms/0%; 298.385ms; 0% | normal | — | YES |
| NORMAL-03 (#23) | 3.776ms/0%; 3.484ms/0%; 197.422ms; 0% | normal | — | YES |
| NORMAL-04 (#24) | 2.491ms/0%; 2.463ms/0%; 286.371ms; 0% | normal | — | YES |
| NORMAL-05 (#25) | 2.528ms/0%; 2.712ms/0%; 201.247ms; 0% | normal | — | YES |
| LATENCY-01 (#26) | 202.900ms/0%; 202.900ms/0%; 809.733ms; 0% | warning | EXTERNAL_HIGH_LATENCY, LOCAL_HIGH_LATENCY, HTTP_SERVER_RESPONSE_DELAY | YES |
| LATENCY-02 (#27) | 202.900ms/0%; 203.500ms/0%; 734.644ms; 0% | warning | EXTERNAL_HIGH_LATENCY, LOCAL_HIGH_LATENCY | YES |
| LATENCY-03 (#28) | 203.000ms/0%; 203.500ms/0%; 1066.528ms; 0% | warning | EXTERNAL_HIGH_LATENCY, LOCAL_HIGH_LATENCY, HTTP_SERVER_RESPONSE_DELAY | YES |
| LATENCY-04 (#29) | 203.400ms/0%; 203.000ms/0%; 804.694ms; 0% | warning | EXTERNAL_HIGH_LATENCY, LOCAL_HIGH_LATENCY, HTTP_SERVER_RESPONSE_DELAY | YES |
| LATENCY-05 (#30) | 202.700ms/0%; 202.700ms/0%; 806.165ms; 0% | warning | EXTERNAL_HIGH_LATENCY, LOCAL_HIGH_LATENCY, HTTP_SERVER_RESPONSE_DELAY | YES |
| LOSS-01 (#31) | 2.865ms/20%; 3.192ms/10%; 690.465ms; 8.333% | warning | LOCAL_PACKET_LOSS, EXTERNAL_PACKET_LOSS, TCP_RETRANSMISSION_HIGH | YES |
| LOSS-02 (#32) | 3.422ms/20%; 3.203ms/20%; 204.828ms; 0% | warning | LOCAL_PACKET_LOSS, EXTERNAL_PACKET_LOSS | YES |
| LOSS-03 (#33) | 2.654ms/0%; 3.361ms/10%; 2280.194ms; 3.333% | warning | EXTERNAL_PACKET_LOSS, HTTP_SERVER_RESPONSE_DELAY | YES |
| LOSS-04 (#34) | 2.698ms/0%; 6.941ms/10%; 363.305ms; 6.667% | warning | EXTERNAL_PACKET_LOSS, TCP_RETRANSMISSION_HIGH | YES |
| LOSS-05 (#35) | 1.989ms/0%; 3.715ms/0%; 260.206ms; 3.125% | normal | — | YES |
| MIXED-01 (#36) | 105.778ms/10%; 104.556ms/10%; 559.636ms; 0% | warning | LOCAL_PACKET_LOSS, EXTERNAL_PACKET_LOSS, LOCAL_HIGH_LATENCY | YES |
| MIXED-02 (#37) | 103.556ms/10%; 102.800ms/0%; 984.275ms; 3.571% | warning | LOCAL_PACKET_LOSS, LOCAL_HIGH_LATENCY, HTTP_SERVER_RESPONSE_DELAY | YES |
| MIXED-03 (#38) | 102.889ms/10%; 103.200ms/0%; 511.540ms; 0% | warning | LOCAL_PACKET_LOSS, LOCAL_HIGH_LATENCY | YES |
| MIXED-04 (#39) | 103.000ms/0%; 104.125ms/20%; 1069.635ms; 2.703% | warning | EXTERNAL_PACKET_LOSS, LOCAL_HIGH_LATENCY, HTTP_SERVER_RESPONSE_DELAY | YES |
| MIXED-05 (#40) | 103.000ms/0%; 104.000ms/10%; 504.033ms; 0% | warning | EXTERNAL_PACKET_LOSS, LOCAL_HIGH_LATENCY | YES |

**평가 A — 설정 조건 탐지:** NORMAL 5/5 정상(오탐 0/5), HIGH_LATENCY 5/5 주의, PACKET_LOSS 4/5 주의, MIXED 5/5 주의. 장애 조건 전체 탐지 **14/15 = 93.3%**. 이는 netem 설정 여부에 대한 집계이며 개별 측정의 사실 오류율이 아니다.

**평가 B — 관측 Evidence 정합성:** **20/20 YES**. LOSS-05의 정상 판정은 관측 손실 0% 및 재전송률 5% 미만과 일치한다. HIGH_LATENCY/MIXED에서 Gateway RTT가 커졌으므로 `LOCAL_HIGH_LATENCY` 발동은 숫자상 타당하다. 코드명에 나타나는 “외부/로컬/서버”를 근본 고장 위치로 단정하지 않는 것이 해석 조건이다.

### 22.11 AI Diagnosis 평가

- 20/20 `available=true`, 모델 20/20 `qwen3.5:4b-q4_K_M`, AI severity와 Rule severity **20/20 일치**. `confidence`는 NORMAL 및 LOSS-05가 `HIGH`, 나머지 주의 사례가 `MEDIUM`; 임의 확률 표기는 없다.
- `primary_cause`는 AI가 자유 생성한 고장 지점이 아니라 Server가 Rule 코드로 구성한 문자열이며 **20/20 Rule과 정확히 일치**한다. 전체 원문 `measured_facts`, `rule_findings`, `hypotheses`, `impact`, `recommendations`, `additional_checks`는 [final_experiment_measurements.csv](reports/final_experiment_measurements.csv)에 보존했다.
- 아래 **Evidence Consistent**는 숫자/Rule 정합성에 더해 AI 자유 서술을 수동 검토한 보수적 등급이다. **YES**는 근거 범위 안의 설명 또는 분명한 가설, **PARTIAL**은 핵심 측정·Rule은 맞지만 원인 지역화·DNS 설정 권고·장비 재부팅 등에서 근거가 약함, **NO**는 핵심 측정값의 명백한 모순을 뜻한다. 결과: **YES 4, PARTIAL 16, NO 0**. PARTIAL을 “실측 숫자 환각”으로 세지 않는다.

| Label | AI Severity | AI Primary Cause | Confidence | Evidence Consistent |
|---|---|---|---|---|
| NORMAL-01 | normal | 규칙 기준에서 뚜렷한 장애 징후가 확인되지 않았습니다. | HIGH | PARTIAL |
| NORMAL-02 | normal | 규칙 기준에서 뚜렷한 장애 징후가 확인되지 않았습니다. | HIGH | PARTIAL |
| NORMAL-03 | normal | 규칙 기준에서 뚜렷한 장애 징후가 확인되지 않았습니다. | HIGH | PARTIAL |
| NORMAL-04 | normal | 규칙 기준에서 뚜렷한 장애 징후가 확인되지 않았습니다. | HIGH | YES |
| NORMAL-05 | normal | 규칙 기준에서 뚜렷한 장애 징후가 확인되지 않았습니다. | HIGH | PARTIAL |
| LATENCY-01 | warning | 관측된 문제: 인터넷 지연, 게이트웨이 지연, HTTP 서버 응답 지연 | MEDIUM | PARTIAL |
| LATENCY-02 | warning | 관측된 문제: 인터넷 지연, 게이트웨이 지연 | MEDIUM | PARTIAL |
| LATENCY-03 | warning | 관측된 문제: 인터넷 지연, 게이트웨이 지연, HTTP 서버 응답 지연 | MEDIUM | PARTIAL |
| LATENCY-04 | warning | 관측된 문제: 인터넷 지연, 게이트웨이 지연, HTTP 서버 응답 지연 | MEDIUM | PARTIAL |
| LATENCY-05 | warning | 관측된 문제: 인터넷 지연, 게이트웨이 지연, HTTP 서버 응답 지연 | MEDIUM | PARTIAL |
| LOSS-01 | warning | 관측된 문제: 게이트웨이 구간 패킷 손실, 외부 구간 패킷 손실, TCP 재전송 증가 | MEDIUM | YES |
| LOSS-02 | warning | 관측된 문제: 게이트웨이 구간 패킷 손실, 외부 구간 패킷 손실 | MEDIUM | PARTIAL |
| LOSS-03 | warning | 관측된 문제: 외부 구간 패킷 손실, HTTP 서버 응답 지연 | MEDIUM | PARTIAL |
| LOSS-04 | warning | 관측된 문제: 외부 구간 패킷 손실, TCP 재전송 증가 | MEDIUM | PARTIAL |
| LOSS-05 | normal | 규칙 기준에서 뚜렷한 장애 징후가 확인되지 않았습니다. | HIGH | YES |
| MIXED-01 | warning | 관측된 문제: 게이트웨이 구간 패킷 손실, 외부 구간 패킷 손실, 게이트웨이 지연 | MEDIUM | PARTIAL |
| MIXED-02 | warning | 관측된 문제: 게이트웨이 구간 패킷 손실, 게이트웨이 지연, HTTP 서버 응답 지연 | MEDIUM | PARTIAL |
| MIXED-03 | warning | 관측된 문제: 게이트웨이 구간 패킷 손실, 게이트웨이 지연 | MEDIUM | PARTIAL |
| MIXED-04 | warning | 관측된 문제: 외부 구간 패킷 손실, 게이트웨이 지연, HTTP 서버 응답 지연 | MEDIUM | PARTIAL |
| MIXED-05 | warning | 관측된 문제: 외부 구간 패킷 손실, 게이트웨이 지연 | MEDIUM | YES |

주요 PARTIAL 사유: #21의 근거 없는 DNS 변경 가설; #22의 DNS Collector partial을 “무시 가능”이라 한 권고; #23·25의 DNS 상태 단정; #26~30의 `DNS_DELAY` 없이 반복된 DNS 설정 변경 권고와 #29의 WAN 고장 지역화; #32의 라우터 자체 손실 추정; #33·34의 DNS 서버 변경 권고(추가로 #33 영향 설명에 베트남어 `thất bại`가 혼입); #36의 대역폭 재분배 제안; #37·38의 장비 재부팅 권고; #39의 라우터 혼잡 추정. #24·31·35·40의 가설은 가설 항목에 있고 핵심 영향·권고가 관측값과 대체로 양립하므로 YES로 보았다. 이 평가는 텍스트 품질에 대한 수동 판단이며 숫자 일치 검사의 대체가 아니다.

### 22.12 Hallucination 검사

- 20개 AI 결과의 **모든 `measured_facts` 518개 항목**을 각 ID의 원본 `metrics`에서 구성한 `section.field=value` 집합과 대조했다. Measurement 단위 분류: **EXACT 20건(항목 518/518), ROUNDING_ONLY 0건, NOT_FOUND 0건, MISINTERPRETED 0건**. `rule_findings`도 저장 Rule 결과와 **20/20 정확 일치**.
- 따라서 존재하지 않는 RTT·손실·DNS 시간·Hop 수·TCP 재전송 숫자를 `measured_facts`에 추가하거나 Gateway/Internet 수치를 바꿔 적은 경우는 발견되지 않았다. Cloudflare `null`과 LOSS-03 System DNS `null`은 숫자로 변환되지 않았다. DNS `resolved_ip`는 조회 대상 IP로만 기록되며 설정 DNS 서버로 표시하지 않는다.
- Traceroute 12개 hop은 **12개 probe 항목**이지 12개 라우터가 응답했다는 뜻이 아니다. 20건 모두 첫 Gateway hop만 응답하고 나머지 11개 항목은 timeout이었다. 이번 20건의 AI 자유 서술에서 timeout을 경로 고장으로 단정한 문구는 찾지 못했다. 다만 다른 자유 가설·권고에서 근거 부족 문제가 남아 있어 “AI 전 문장이 검증 완료”로 발표하지 않는다. `measured_facts`의 수치 정확성과 자유 서술의 인과 정확성은 별개다.

### 22.13 Rule Engine + AI 역할

`Measurement → Rule Engine → AI`. Rule Engine은 동일 Threshold를 일관되게 적용하고 발동 숫자를 finding에 남긴다(20/20 재현). AI는 그 사실과 Rule 결과를 바탕으로 영향·추가 확인·사용자용 설명을 만든다(20/20 이용 가능). 하지만 #26~30의 DNS 권고처럼 자유 문장이 근거를 넘어갈 수 있어 AI가 Rule을 대체하거나 실제 장애 원인을 확정하지 않는다. 발표에서는 **실측 사실 → Rule 판단 → 검증되지 않은 AI 가설/권고**를 시각적으로 분리한다.

### 22.14 대표 Measurement

- **NORMAL #22**: Internet RTT 2.682 ms, Loss 0%, TTFB 298.385 ms, Rule 정상. DNS partial을 “무시 가능”이라 한 AI 권고는 캡처에서 그대로 신뢰하지 말고 주석으로 한계를 알린다.
- **LATENCY #26**: Gateway/Internet RTT 모두 202.900 ms, TTFB 809.733 ms, 두 지연 Rule과 HTTP TTFB Rule. 설정 지연이 Gateway에도 나타난다는 점을 설명하기 좋다. AI의 DNS 설정 권고는 근거 부족.
- **LOSS #31**: Internet Loss 10%, Gateway Loss 20%, TCP 재전송률 8.333%, 관련 Rule 3개. 4종 중 손실+재전송을 가장 명확히 보여준다. 재전송률은 조건 평균 4.292%보다 높으므로 대표 예시는 평균값이 아니다.
- **MIXED #36**: Gateway/Internet RTT 약 105/105 ms, 두 방향 Loss 10%, TTFB 559.636 ms, 관련 Rule 3개. 이 단일 표본의 TCP 재전송률은 **0%**이므로 MIXED 평균 재전송률 1.255%와 혼동하지 않는다.
- 제안된 22·26·31·36을 **시각적 대표 사례**로 유지하되 조건 평균을 대표하는 통계 사례로 주장하지 않는다.

### 22.15 PPT 그래프 데이터

- [final_experiment_summary.csv](reports/final_experiment_summary.csv): 조건별 평균 Internet RTT(Graph A), Internet Loss(Graph B), HTTP TTFB(Graph C), TCP 재전송률(Graph D), Rule normal/warning/critical 건수(Graph E)와 DNS 유효 n.
- [final_experiment_measurements.csv](reports/final_experiment_measurements.csv): ID별 19개 측정 Metric, 원본 `null`, Collector 상태, Rule·AI 필드 및 정확성 플래그.
- [final_experiment_stats.csv](reports/final_experiment_stats.csv): 조건×19 Metric의 평균·표본 SD·최소·최대·유효 n. CSV의 `null`은 결측이고 **0과 다르다**.
- 발표용 요약: “NORMAL 평균 Internet RTT는 **2.827 ms**였다. 200 ms 지연 조건에서 RTT는 **203.120 ms**(+200.293 ms), HTTP TTFB는 **3.213배**가 됐다. 10% 손실 조건에서는 Internet Ping 손실 평균 **10.000%**, TCP 재전송률 평균 **4.292%**가 관측됐다. MIXED에서도 RTT **103.736 ms**, Internet Loss **8.000%**, HTTP TTFB **725.824 ms**로 증가했다.”
- PPT 추천 캡처: Overview의 조건별 최신 상태, #22 정상 상세, #26 양 방향 RTT·Rule, #31 손실·재전송, #36 혼합 지표, AI의 사실/규칙/가설/권고 분리, ID21~40 History 그래프. AI의 약한 권고가 표시될 때는 한계 주석을 붙인다.
- 현재 Frontend/API 확인: `192.168.0.201:3001/` HTTP 200, API proxy의 대표 진단 #22·26·31·36 모두 HTTP 200. 최근 진단 20개는 ID 40→21, 해당 Agent History의 마지막 20점은 ID 21→40의 시간 오름차순이다. Frontend 코드는 개요·측정 상세·AI 진단·이력을 이 데이터로 렌더링한다. 마지막 `last_seen` 이후 5분을 넘어 현재 Overview의 Agent 표시는 **오프라인**이 정상이며, 온라인 캡처에는 새로운 실제 Agent 측정이 필요하다. 실제 브라우저 픽셀 렌더링은 이번에 확인하지 못했다.

### 22.16 실험 한계

조건당 **5회**, Agent **1대·네트워크 1곳**이라 일반화가 제한된다. netem이 `wlp1s0` 전체에 적용되어 Gateway와 Internet을 동시에 지연·손실시켰다. 짧은 Ping 표본으로 설정 손실률과 개별 관측 손실률이 다를 수 있다(LOSS-05 0%). TShark 캡처가 짧고 패킷 수가 적어 TCP 재전송률 변동이 크다. Cloudflare DNS Collector는 20건 모두 partial이며 일부 System/Google DNS도 결측이다. System DNS `0 ms`의 raw parser 근거는 Server에서 확인되지 않았다. iperf3 처리량은 측정하지 않았다. TTFB는 네트워크+서버 요인이 섞인 종합 지표다. 후속 실험은 표본·환경 확대, DNS raw 결과 보관, 캡처 구간 확대, iperf3, 구간별 지연 주입으로 보완할 수 있다.

### 22.17 최종 결론

**데이터 파이프라인은 실험 20건 모두 저장→Rule→Ollama AI→History/API 공급까지 성공**했다. 설정 장애 탐지는 14/15(93.3%), 정상 오탐은 0/5이며, Rule 결과는 원본 Metric에 20/20 일치한다. AI 실측 사실과 Rule finding도 20/20 정확하지만 자유 서술 16건은 근거 약한 원인/권고가 포함되어 발표 시 가설과 한계를 명시해야 한다. LOSS-05는 설정상 장애가 있어도 그 회차의 실제 관측값은 정상 범위인 정당한 예외다. Dashboard HTTP/API 데이터 공급은 검증했으나 대표 4건의 **실제 브라우저 시각 캡처는 아직 미실시**했다. 원본 데이터·Threshold·AI 응답은 이 분석에서 변경하지 않았다.

## 23. NetDoctor v2 — Network Health Score (2026-10-03)

### 23.1 기능 목적

실측값에서 정량 품질 점수와 감점 근거를 계산해 `점수 → 원인 → 실제 수치`를 추적한다. AI가 점수를 결정하지 않는다. 이 점수는 NetDoctor 내부의 설명 가능한 진단 보조 지표이며 공식 통신 품질/SLA 지표가 아니다.

작업 시작 시 저장소는 첫 커밋 없이 staged/unstaged 코드가 혼재했다. 기존 코드·보고서·실험 CSV를 첫 커밋 **32a08f5**에 보존하고 **v1.0-mvp** 태그를 만들었다. 작업 브랜치는 **feature/health-score**다. `.env`, DB, PCAP, 모델, node_modules는 포함하지 않았다. v1 Backend/Frontend Docker 이미지에도 `:v1.0-mvp` 보존 태그를 붙였다. DB 백업 `reports/netdoctor-v1-20261003.sql`은 권한600/Git 제외이며 비밀번호·API 키를 보고서에 기록하지 않았다.

### 23.2 Score Architecture

```text
Agent Measurement (v1 schema 유지)
    → Measurement 저장
    → 기존 Rule Engine (rules.yaml 유지)
    → Score Engine (별도 health_score.yaml)
    → health_scores 저장 (snapshot/hash/version/evidence)
    → Ollama (읽기 전용 점수 근거)
    → 기존 AI 구조 저장
    → 기존 REST/History + Score API → Dashboard
```

주요 파일: `backend/app/scoring.py`(순수 계산·설정 검증), `health_score.yaml`(정책), `score_store.py`(버전별 불변 저장), `models.py`/`schemas.py`(DB/API), `tools/backfill_health_scores.py`(범위 검증·Backfill·CSV), `frontend/.../HealthScorePanel.jsx`(점수/근거), 기존 chart/table/API 연결 파일. 새 라이브러리는 설치하지 않고 기존 PyYAML/Pydantic/SQLAlchemy/Bklit와 표준 라이브러리를 사용했다. 구현 전 정책은 `reports/health_score_design.md`에 남겼으며 실험 점수에 맞춰 수정하지 않았다.

### 23.3 Category 정의

| 영역 | 실측 근거 | 해석 |
|---|---|---|
| Local Network | Gateway 평균 RTT/손실 | 첫 구간 방향의 관측 품질. Gateway 장비 고장 확정은 아님 |
| Internet | Internet 평균 RTT/손실 | 해당 측정 목적지에 대한 품질. 모든 Internet 서비스의 품질은 아님 |
| DNS | System/Google/Cloudflare 시간 | 성공한 응답의 성능. Collector availability와 분리 |
| TCP | 재전송%, Duplicate ACK/RST/Zero Window | 짧은 캡처의 관측 품질. 표본 한계 표시 |
| HTTP | Status/TTFB/Total/Connect/TLS | 요청 결과/시간. 서버 자체 처리 시간만 분리하지 않음 |

v1 Measurement에 없는 Link/Interface up/down 상태를 추정하지 않는다. Traceroute timeout/hop 수만으로 품질 감점하지 않는다. HTTP 수집 실패로 실제 응답값이 없으면 원격 서버 장애를 단정하지 않고 미측정으로 처리한다.

### 23.4 Weight

Local **.20**, Internet **.25**, DNS **.15**, TCP **.20**, HTTP **.20**. 도달성/전송 관측에 합계65%, DNS15%, HTTP20%를 배정한다. 환경별 절대 품질 또는 고장 확률을 학습한 가중치는 아니다. 합계1.0/양수/유한값/정확히5개 Category를 Pydantic으로 검증한다.

점수 범위는0~100. severity는 **80 이상 normal / 60 이상 warning / 60 미만 critical**, 계산 불가는 unknown. 기존 Rule severity는 변경하지 않으며 별도 “규칙 경보”로 표시한다. 종합 점수의 normal이 모든 영역의 normal을 보장하지 않는다.

### 23.5 Deduction Rule

| Metric | 구간과 감점 |
|---|---|
| Gateway RTT(ms) | >20:25, >100:40, >200:50, >500:65 |
| Internet RTT(ms) | >150:30, >200:50, >500:65 |
| Gateway/Internet Loss(%) | ≥3:25, ≥5:35, ≥10:45, ≥20:60, ≥50:75, ≥100:100 |
| DNS 응답(ms) | >300:25, >600:40, >1500:60; resolver별 최대1개 |
| TCP 재전송(%) | ≥1:10, ≥5:25, ≥10:40, ≥20:60, ≥50:80, ≥100:100 |
| Duplicate ACK(건) | ≥3:10, ≥10:25; 재전송과 같은 그룹의 최대1개 |
| RST / Zero Window(건) | RST≥1:10, ≥5:25; Zero Window≥1:15, ≥5:30 |
| HTTP status | ≥400:30, ≥500:60 |
| HTTP timing(ms) | TTFB>800:25/>1500:40/>3000:60; Total>2000:25/>4000:40/>8000:60; Connect>500:20/>1500:35; TLS>1000:20/>3000:35 |

각 Metric은 해당 값이 만족하는 가장 큰 구간1개만 선택한다. HTTP 시간은 겹치는 왕복 단계이므로 timing 그룹의 **최대 감점1개**만 적용한다. 독립 그룹 합계는100에서 제한한다. 실제 적용 `points`와 제한 전 `assessed_points`를 함께 저장하고 **100−Σpoints=영역 점수**를 보장한다. Loss100%는 큰 감점부터 적용되어 같은 방향 RTT가 추가 감점되지 않는다. `top_causes.weighted_points = points × 영역 가중치 / 유효 가중치 합`으로 전체 감소분도 추적한다.

감점 객체에 code, 원본 Metric 필드, 실측값/단위, 비교 operator/threshold, 적용 points, reason, group이 들어간다. 동일한 원인에서 RTT·손실·TCP·HTTP가 함께 영향을 받을 수 있지만 인과적으로 동일하다고 임의 병합하지 않는다. 그룹 내 중복 제거와 가중치/영역 상한으로 제한하며 완벽한 인과 모델이라고 주장하지 않는다.

### 23.6 Missing Data 처리

- null/NaN/Infinity/음수/설정 유효 범위 위반/비숫자는 제외한다. 실제0은 유지한다. TCP captured_packets=0이면 다른 필드가0이어도 TCP Score는 null이다.
- 품질 지표가 전혀 없는 영역은 score=null/available=false. Category coverage는 설정된 품질 지표 중 유효 비율이며 collector partial/error는 별도 notes/quality로 표시한다.
- Cloudflare 시간 null만으로 DNS를 감점하지 않는다. 실제20건 DNS Score100은 **성공한 응답에서 지연 경계 미초과**라는 뜻이다. DNS coverage는18건2/3, #33과#34는1/3이다. #33은 System DNS, #34는 Google DNS가 추가로 null이었다. 2026-10-04 검수에서 기존 “19건2/3, #33만1/3”이라는 보고서 집계 오류를 정정했으며 원본과 저장 Score는 수정하지 않았다. 실제 System DNS0ms의 parser 한계도 v1 보고서와 동일하다.
- TCP captured_packets<50 또는 확인 불가는 low_sample/partial이고 표본 수 자체로 감점하지 않는다. 표본은 실제20건에서 모두50 미만이다.
- Overall은 unavailable 영역을 제외해 가중치를 정규화한다. 유효 영역의 원래 가중치 합이0.50 미만이면 Overall=null. Overall coverage는 누락을 포함한 원래 가중치로 계산하므로 높은 점수와 낮은 범위를 구별한다. 실제18건 Overall coverage95%, #33/#34는90%; v1 quality는 모두partial다.

### 23.7 Database

새 테이블 **health_scores**만 추가했다. measurement_id FK, score_version, overall_score/severity, result(JSONB: Category/deduction/evidence/coverage), config_snapshot(JSONB), config_hash(SHA256), created_at을 저장한다. `(measurement_id,score_version)` UNIQUE와 전체 점수 범위 CHECK가 있다. 기존4개 테이블의 실험 행은 수정하지 않았다.

같은 버전은 동일 정책으로 유지하고 YAML 변경 시 score_version을 바꾼다. 기존 버전에 다른 config hash를 덮어쓰는 작업은 시작/Backfill 시 거부한다. 새 버전은 기존 결과를 보존하면서 별도 행으로 추가할 수 있다. 기존 Score는 GET 시 재계산하지 않는다.

### 23.8 API

- 신규 `GET /api/v1/measurements/{id}/health-score`; 동일 X-NetDoctor-Key 인증, Pydantic HealthScoreOut.
- 기존 Measurement 응답에 optional health_score를 추가했다. Diagnosis의 measurement와 Agent History도 동일한 저장 결과를 반환한다. v1 Agent POST 입력/schema_version1.0/기존 Endpoint는 유지한다.
- 미계산 이력은 health_score=null이고 별도 Score API는404다. 신규 측정은 Rule/Score를 AI 전에 저장하므로 Ollama 중단 시에도 조회된다.
- 실제 대표22/26/31/36의 Frontend proxy Score API가 모두200이고 점수와 감점 원본값을 대조했다.

### 23.9 Dashboard

개요와 측정 상세에 전체 점수/텍스트 severity/5개 Category/coverage/partial 상태/표본 한계/감점 상세를 추가했다. 영역 또는 주요 원인 클릭으로 `100−감점=점수`, 실측값, Threshold, 원본 필드까지 확인한다. 기존 KPI·Rule 경보·측정표·AI·테마·Agent 선택·새로고침은 유지한다. Headless Firefox에서 실제20건을 연결해 대표4건과7개 History 그래프(점수+기존6개), 밝은 테마/새로고침을 확인했다. JS 오류0건. 폭500px에서4개탭 모두 문서 가로 넘침이 없었다. Chart resize 갱신을 기다린 뒤 검사했다.

PPT용 실제 캡처: `reports/screenshots/health-score-22.png`, `health-score-26.png`, `health-score-31.png`, `health-score-36.png`. 키 입력은 password 마스킹 상태이고 API 키 값을 저장하지 않았다. 최근 측정/History 표의 미계산값은0이 아닌 “미계산”이다. 기존 자연스플라인의 측정점 사이 overshoot를 피하도록 Line에 단조 보간을 적용했다. 점수/원본 측정값은 바뀌지 않는다.

### 23.10 AI 연동

신규 측정에서 계산된 Overall/Category/주요 감점만 읽기 전용으로 AI 입력에 추가했다. System Prompt는 AI의 점수/가중치/감점 생성·수정·반환을 금지한다. 기존 StructuredAI 출력 필드와 서버 생성 measured_facts/rule_findings/primary_cause는 유지한다. 기존 ID21~40의 AI를 재저장하지 않았다. Mock 응답이 health_score=999를 반환해도 AI 출력 모델에서 제거하고 저장 Score를 대체할 수 없음을 테스트했다. 실제 Ollama 검증 호출은 기존 ID26을 참고하는 **비저장 검증 요청**으로 성공했다: available=true, warning/MEDIUM, Rule 기반 primary_cause 유지, AI 출력에 점수 필드 없음. 기존 저장 AI 행은 호출 후에도 해시가 같다.

### 23.11 기존 20건 Backfill

default dry-run에서 계산20/INSERT0 → `--apply` INSERT20 → 재실행 INSERT0. 범위21~40과 실제 Agent ID를 모두 검증한다. 범위 누락/다른 Agent/동일 버전 정책 충돌은 쓰기 전 거부한다. 기존 Measurement/Rule/AI 전체 행의 SHA256은 작업 전후 **5b070c64cf396fccdb7ddfd749a3fccef4930913cfef04b6cdbe9450339e70ca**로 일치했다.

핵심 명령: `docker compose build backend frontend`; `docker compose up -d --no-deps backend frontend`; `docker compose exec -T backend python -m app.tools.backfill_health_scores --dry-run`/`--apply`. PostgreSQL은 재생성하지 않았고 기존 볼륨을 유지했다. Source CSV는 동일 DB에 연결하는 프로젝트 Python의 `--dry-run --csv reports/health_score_experiment.csv`로 저장된 결과를 내보냈다.

### 23.12 Condition별 Score 결과

각 Condition n=5, 점수 계산 유효 n=5. DNS 측정 coverage와 TCP 표본은 별도 partial이다.

| Condition | Overall | Local | Internet | DNS | TCP | HTTP |
|---|---:|---:|---:|---:|---:|---:|
| NORMAL | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 |
| HIGH_LATENCY | 73.50 | 50.00 | 50.00 | 100.00 | 100.00 | 80.00 |
| PACKET_LOSS | 80.25 | 76.00 | 61.00 | 100.00 | 82.00 | 92.00 |
| MIXED | 75.90 | 33.00 | 70.00 | 100.00 | 94.00 | 90.00 |

대표 사례(Overall / Local / Internet / DNS / TCP / HTTP): **#22:100/100/100/100/100/100**, **#26:72.5/50/50/100/100/75**, **#31:69.75/40/55/100/65/100**, **#36:71.75/15/55/100/100/100**.

해석: NORMAL 5건은 불필요한 성능 감점이 없다(측정 범위의 partial은 유지). LATENCY는 Gateway/Internet 양 방향 RTT에서 각50점 감점, TTFB 경계 초과4건에 HTTP25점 감점이다. LOSS는 Internet 손실로 Internet40~100점, TCP 재전송과 일부 RST로 TCP65~100점이다. #35는 이번 Loss0%이고 재전송3.125%에 따른 TCP10점 감점만 있어 Overall98이다. MIXED는 Gateway 지연과 손실로 Local 평균33까지 낮아지지만 Overall은68~83으로0에 가깝지 않다.

LOSS 평균80.25를 “장애를 모두 놓침” 또는 “모두 정상”으로 취급하지 않는다. 개별 Score는69.75/73/78.75/81.75/98이고 Rule은4warning+1normal이다. #34의 Overall81.75는 Internet55/TCP65의 이상이 다른 영역100과 평균되며 완화된 결과, #35는 Ping에서 손실이 관측되지 않은 정당한 예외다. MIXED #38/#40도 Overall≥80이지만 Local/Internet 감점과 Rule 경보를 계속 표시한다. 평균에 의한 국소 이상 희석을 한계로 공개하며 결과에 맞춰 식을 조정하지 않았다.

PPT 데이터: `reports/health_score_experiment.csv`(20건, 실측ID·Condition·전체Score·주요감점·Coverage·Version/hash), `health_score_summary.csv`(Graph1 Overall 평균, Graph2 Category 평균/n), `health_score_representatives.csv`(Graph3 대표4건). 실험명은 사용자 지정 Mapping을 CSV에만 붙이며 Measurement에는 저장하지 않는다.

### 23.13 테스트

최종 Python 테스트는 **기존15/15 + 신규26/26 = 41/41** 통과. Frontend 기존1+신규1=**2/2**, Vite/Docker build 성공. 기존 API/Rule 테스트 파일은 수정하지 않았다. 별도 lint script는 기존 프로젝트에 없다. 기존 FastAPI on_event/anyio deprecation과 약548kB JS chunk 경고는 기능 실패가 아니다.

| 목적 | 입력 | 예상 | 실제 결과 |
|---|---|---|---|
| v1 회귀 | 기존15개 테스트 | API/auth/Rule/AI/Fallback 유지 | 15/15 성공 |
| 범위/감점 추적 | 정상/지연/손실/혼합/극단값 | 0~100, 100−Σpoints 일치 | 성공 |
| 설정 검증 | 잘못된Weight/구간/Severity | 명확한 ValidationError | 성공 |
| 결측 처리 | DNS/TCP null, NaN, 음수, 전체결측 | null/coverage/partial, 0으로 대체하지 않음 | 성공 |
| 표본/중복 감점 | DNS partial, TCP30/0개, 여러HTTP 시간 | partial/미계산, group 최대1개 | 성공 |
| 신규 업로드/API/AI 장애 | SQLite test DB + 기존JSON + Ollama unavailable | Score 먼저 저장,401/200/404,History/Diagnosis 연결 | 성공 |
| 버전/영속성/Backfill | dry-run/apply/repeat/conflict/new-version | 0/20/0 insert, 충돌 거부, 구버전 보존 | 성공 |
| 실제 DB Backfill/재시작 | 실제ID21~40, PostgreSQL restart | 점수20건 유지, 원본해시 불변 | 성공 |
| AI 읽기 전용 | 가짜모델점수999 + 실제Ollama ID26 비저장 호출 | 모델점수 제거, 실제구조응답 성공 | 성공 |
| Dashboard/History | 실제4개대표,7차트,테마/새로고침/500px | 실측점수·감점 정상표시, JS 오류 없음 | 성공 |

신규 POST는 격리된 테스트 DB에서 검사했으며 운영DB에 Fixture를 추가하지 않았다. 실제 Agent의 다음 신규 업로드에서 v2 Score 자동 저장을 다시 확인할 수 있다. PostgreSQL 재시작 후 actual History는21→40 정렬 및 Score20건을 유지하고 원본 Measurement/Rule/AI 해시는 불변이었다.

### 23.14 문제와 해결

- v1에 Commit이 없었음→검증된 현 상태를 초기Commit/Tag로 명시적으로 보존하고 비밀값을 제외했다.
- 동일 현상의 이중 감점→최대1개의group과 실제 적용 감점을 저장한다.
- dry-run 시 새Table이 없을 가능성→존재 확인과 기존Score relationship 로딩 억제로 Table 생성/쓰기 없이 계산한다.
- PostgreSQL JSONB의 Category key 순서 변화→UI는 Local/Internet/DNS/TCP/HTTP의 고정 표시 순서를 사용한다. 수치·정책은 바꾸지 않는다.
- 기존REPORT23은 Bklit 개편이었음→본문을 남겨24로 이동하고, 요청대로 v2를23에 추가했다.
- 자연스플라인이 점수 측정점 사이에서100초과처럼 보일 가능성→기존Line을 단조 보간으로 그려 범위 밖 overshoot를 방지한다. 측정값/점수/임계값은 그대로다.
- CSV 기본 CRLF가 Git whitespace 검사에 걸림→내보내기 줄 끝을LF로 지정하고 UTF-8 BOM은 유지했다. CSV 숫자와 원본DB값은 바꾸지 않는다.

### 23.15 한계

기본 경계는 환경/목적지에 따라 수동 설정한 값이며 절대 품질이 아니다. 작은 표본/Cloudflare partial/실제 System DNS0ms의 유래 미검증은 v1과 같다. RST는 정상 종료에서도 나타나므로 원인을 단정하는 근거로 쓸 수 없다. 여러 Category가 같은 netem 영향을 받을 수 있다. 국소Critical이어도 Overall 평균이 높아질 수 있어 단일 점수만으로 판단하지 않는다. Link 상태/Traceroute 확정 장애/iperf 점수는 근거 부족으로 도입하지 않았다. 기능 추가 전11건은 미Backfill이므로 점수 미계산으로 표시한다.

### 23.16 향후 개선

환경별 경계의 타당성을 검증하고 표본 수를 늘린다. Score Version을 변경해 비교하고 이전 결과는 보존한다. RST 연결 문맥·interface/link 실측·짧은 capture 개선·DNS raw 결과를 Agent에서 얻었을 때 평가 대상을 확장한다. 국소 장애를 중시하는 critical guard/min-category 표시는 다음 버전의 명시적 정책으로 검토한다. 현재20건을 재라벨/재측정/재AI 저장해 결과를 바꾸지 않는다.

## 24. NetDoctor v2.1 Health Score 정책 개선 (2026-10-04)

### 24.1 v1 검수에서 발견된 문제

가중 평균만으로 상태를 판정하면 일부 영역의 장애가 희석된다. 실제 #38은 Local15/Overall83인데 v1 normal, #34는 Internet Loss10%/TCP 재전송6.667% 및 Rule warning인데 Overall81.75로 v1 normal이었다. 단계형 경계의 큰 점프, 상관 Metric을 독립 장애로 오해할 가능성, 작은 TCP 표본, 단독 RST 감점, snapshot 재로딩 시 숫자 표기 차이도 검토했다.

현재 v1 구현 commit **2452a0e**를 **v2.0-health-score-v1** 태그로 보존하고 **feature/health-score-v1-1**에서 작업했다. 기존 v1.0-mvp 태그는 유지한다. Backend/Frontend 이미지는 `:v2.0-health-score-v1` 태그로 남겼고, 작업 전 DB 백업은 `reports/netdoctor-v2-before-v1-1-20261004.sql`(권한600, Git 제외)에 저장했다. API 키/비밀번호는 보고서·CSV·캡처에 기록하지 않았다.

구체 정책은 실험의 v1.1 점수를 추출하기 전에 `reports/health_score_v1_1_design.md`에 고정했다. 기존 가중치/Rule threshold를 변경하거나 측정값/기존 AI를 결과에 맞게 수정하지 않았다.

### 24.2 Score와 Status 분리

```text
Measurement ──→ Category Scores ──→ Weighted Overall Score ──→ Base Severity
                         │                                      │
                         └──→ Category Guard ────────────────────┤
Stored Rule Diagnosis ───────→ Rule Guard ────────────────────────┤
                                                               ▼
                                                    Final Health Status
Coverage / TCP sample_size ──→ Data Quality (별도)
Score + Status + Quality + Guard/Deduction Evidence ──→ DB / API / Dashboard
```

Score는 전체 품질의 가중 평균, Status는 관측 장애의 상태, Quality는 수집 범위/표본의 해석 한계다. 가중치는 Local20% / Internet25% / DNS15% / TCP20% / HTTP20% 그대로다. Base Severity는 ≥80 normal / ≥60 warning / <60 critical이며 최종 Status는 Guard와 Base 중 심각한 쪽이다. 호환 필드 `overall.severity`는 v1.1의 최종 Status이고 `base_severity`/`status`를 추가했다. 모든 숫자 점수는0~100이며 Guard가 점수를 임의 감액하지 않는다.

### 24.3 Severity Guard

설정 파일 `backend/app/health_score_v1_1.yaml`에서 관리한다.

| 관측 조건 | 최종 상태 최소값 | Guard code |
|---|---|---|
| 유효 Category <40 | warning | critical_category |
| 유효 Category <60, 위 조건 없음 | warning | warning_category |
| 저장 Rule warning | warning | rule_warning |
| 저장 Rule critical | critical | rule_critical |

Guard는 낮은 점수를 수정하거나 기존 Rule을 재작성하지 않는다. Guard threshold를 만족하면 Base가 이미 warning이어도 근거를 기록한다. Rule 없는 운영 저장/Backfill은 거부하여 누락 Rule을 normal로 추측하지 않는다. 순수 계산에서 Rule을 생략한 경우에는 Category Guard만 평가했다는 note가 있다. unavailable Category는 낮은 수치로 대체하지 않는다.

실제 #34는 **Score82.75 / Base NORMAL / Final WARNING**으로 평균 희석을 해결했다. #38은 선형 감점으로 Base 자체가 WARNING(78.73)이 됐지만 Local<40 및 Rule warning Guard도 기록한다. 별도 합성 테스트에서는 Overall>80, Local<40, Rule normal이어도 Final WARNING임을 검증했다.

### 24.4 Piecewise Deduction

기존 v1의 **양수 경계→감점 anchor를 보존**하고 인접 anchor 사이만 선형 보간한다. 감점0 시작점은 첫 v1 경계의 절반, Loss는0%로 정했다. 신규 정책을 기존20건 점수에 fitting하지 않았다. 마지막 anchor 이상은 최대 감점에 포화되며 같은 Metric에 여러 구간을 합산하지 않는다.

| 선형 Metric | 0 감점 시작 | 양수 anchor(값→감점) |
|---|---:|---|
| Gateway RTT(ms) | 10 | 20→25, 100→40, 200→50, 500→65 |
| Internet RTT(ms) | 75 | 150→30, 200→50, 500→65 |
| Gateway / Internet Loss(%) | 0 | 3→25, 5→35, 10→45, 20→60, 50→75, 100→100 |
| TCP retransmission(%) | 0.5 | 1→10, 5→25, 10→40, 20→60, 50→80, 100→100 |
| HTTP TTFB(ms) | 400 | 800→25, 1500→40, 3000→60 |

예: TTFB799ms 감점24.9375, 801ms 감점25.0214로 기존0→25점 점프를 없앴다. Loss0%는 감점0이다. DNS/ACK/RST/Zero Window/HTTP status/Total/Connect/TLS는 단계형을 유지하며, HTTP 시간/TCP 재전송·ACK/DNS resolver 최대1개 그룹과 영역100점 한도도 유지한다. `calculation`, `range_start/end`, `value`, 소수 `points/assessed_points`를 저장해 구간을 설명한다.

### 24.5 Cause Group

감점에 설명용 `cause_group`을 추가했다: RTT=LATENCY, HTTP timing=LATENCY_EFFECT, Ping Loss=PACKET_LOSS, 재전송/ACK/Zero Window=TCP_DEGRADATION. UI에서 LATENCY와 LATENCY_EFFECT를 “지연 관련 관측 효과”, PACKET_LOSS와 TCP_DEGRADATION을 “손실·전송 품질 관측”으로 묶고 모든 효과와 전체 가중 감점을 보여준다. cause_group은 동일 원인의 증명이나 독립 장애 개수가 아니다.

Category 간 상관 감점은 실제 여러 계층의 품질 저하를 나타내므로 숫자 계산에 유지했다. #26의 Gateway/Internet/HTTP 지연이 하나의 netem 영향을 함께 받을 수 있음을 그룹으로 설명하되 감점을 인과 모델로 상쇄하지 않는다. “이중 감점이 완전히 제거됐다”라고 주장하지 않는다.

### 24.6 TCP Low Sample

TCP `sample_size`와 `quality=low_sample`을 별도로 제공한다. YAML 최소50개보다 작은/미확인 표본은 낮은 해석 신뢰도를 표시한다. TCP 점수는 유지하고 Overall TCP 가중치20%도 그대로다. 실험20건은 모두25~40개 캡처로 low_sample이며 Overall은 모두low_confidence다. confidence는 통계 확률이나 AI 신뢰도와 동일한 값이 아니다.

RST1건의 기존10점 감점을 제거했다. **RST≥5**에 추가로 재전송≥5%, Duplicate ACK≥3, Zero Window≥1 중 하나가 있어야25점 감점한다. 반복 RST만 있거나 RST1건과 재전송이 있어도 단독 RST 감점은 없다. RST 관측 자체는 evidence/notes에 남고 정상 종료/서비스 동작에서도 발생할 수 있음을 알린다. 변경 이유는 단일 RST를 장비 장애처럼 과대해석하지 않기 위함이지 특정 실험 점수를 올리기 위함이 아니다.

### 24.7 Coverage / Data Quality

v1의 결측/coverage/가중치 재정규화 정책을 유지한다. null은0ms/100점으로 변환하지 않으며 실제0ms는 그대로 유지한다. unavailable 영역을 제외한 가중치로 Overall을 계산하되 유효 가중치 합<0.50이면 Score=null이다. Coverage는 제외 영역을 포함한 원래 가중치로 계산하여 누락을 숨기지 않는다.

Cloudflare DNS null은20건 모두 존재하고 그 자체로 성능 감점하지 않는다. #33은 System DNS, #34는 Google DNS도 null이다. DNS coverage는18건66.67%, 2건33.33%; Overall coverage는18건95%, 2건90%다. 성공한 Resolver의 응답에 감점 조건이 없으므로 DNS Score100이며 “모든 Resolver 정상”이라는 뜻이 아니다. 실제20건은5영역 모두 계산 가능하므로 가중치 재정규화는 불필요했고 결측 Category 재정규화는 자동화 테스트에서 검증했다.

Overall Quality는 unavailable 우선, 그다음 low_sample Category가 있으면 low_confidence, 결측/Collector 제한만 있으면 partial, 모두 충족하면 complete다. 따라서 실험20건은 low_confidence이며 coverage와 DNS partial도 별도로 표시된다. Quality만으로 장애 Status를 만들어내지 않는다.

### 24.8 Hash Canonicalization

v1.1부터 재귀적으로 key를 정렬하고 정수와 동일한 실수는 정수로 표현한 canonical JSON을 SHA256으로 해시한다. `0`/`0.0`, key 순서 차이는 동일 Hash이며 실제 경계/Weight 변경은 다른 Hash다. 기존 v1은 legacy payload/직렬화를 별도로 유지해 저장 Hash를 바꾸지 않았다.

- v1: `c64ff81ece540b6c0e8433f979e9422c13a40e2260793a62bc995368ab10df18`
- v1.1: `96d12b4a02c4859be65fa65ffb56e1bcda6bd6d60f9098f75c75602380f71ed1`

동일 버전 정책 충돌은 시작/Backfill/저장에서 거부한다. v1의 legacy Hash에 포함되지 않는 신규 Guard/선형/RST 지원/Cause Group 정책을 v1 이름으로 설정하는 것도 검증 단계에서 거부한다. float 표현 정규화는 정책 값 자체의 반올림이 아니다.

### 24.9 DB Versioning

기존 health_scores 테이블/JSONB 및 `(measurement_id,score_version)` UNIQUE를 사용했다. v1행20개 + v1.1행20개를 공존시켰으며 원본 Measurement/Rule/AI/v1 Score 행은 UPDATE/DELETE하지 않았다. v1.1 결과에 Base/Final/Guard/Quality/Cause Group/선형 구간 근거를 저장했다. 기존v1 정책을 재계산한20건의 점수·감점·측정 근거·coverage·정책 Hash가 저장값과 일치함을 확인했다.

Backfill: dry-run20건/INSERT0 → apply20건/INSERT20 → repeat20건/INSERT0. 범위21~40, 실제 Agent ID 및 모든 기존 Rule 존재를 검증한다. CSV 비교 내보내기도 두 버전 저장 결과를 읽고 DB를 변경하지 않는다. 주요 명령:

```bash
docker compose build backend frontend
docker compose up -d --no-deps backend frontend
docker compose exec -T backend python -m app.tools.backfill_health_scores --dry-run
docker compose exec -T backend python -m app.tools.backfill_health_scores --apply
docker compose exec -T backend python -m app.tools.backfill_health_scores \
  --dry-run --comparison-csv /tmp/health_score_v1_vs_v1_1.csv
docker compose cp backend:/tmp/health_score_v1_vs_v1_1.csv reports/health_score_v1_vs_v1_1.csv
```

실험20행 각각을 포함한 테이블 전체 JSON SHA256은 작업 전후 동일했다:

| 보존 대상 | 작업 전후 동일 Hash |
|---|---|
| measurements | 60309182f840e7c9e9569ad65feb13e9e6e0512696a70a6ea01ddd45f1a38ddc |
| rule_diagnoses | 8f84b7d406dda42fe23df0439c2f6df2395e9d64977838c98dcbcaed297efbae |
| ai_diagnoses | f046c20992493872b7202f4ed1ecc069cc31d826c38cbd9ef1a5132a095cade4 |
| health_scores(v1) | 6b2a7d8e0e40df66767f389ad09c3aaaa17090323a278ea3985250c729d734ac |

### 24.10 v1 vs v1.1 비교

아래는 **DB에 저장된 Overall Score**의 조건별 산술평균(n=5), 두 상태 열은 NORMAL/WARNING/CRITICAL 건수다. 원본4종 실험과 기존20개 AI 결과는 변경하지 않았다.

| Condition | v1 평균 | v1.1 평균 | v1 상태 N/W/C | v1.1 최종 상태 N/W/C |
|---|---:|---:|---|---|
| NORMAL | 100.00 | 100.00 | 5/0/0 | 5/0/0 |
| HIGH_LATENCY | 73.50 | 72.35 | 0/5/0 | 0/5/0 |
| PACKET_LOSS | 80.25 | 78.64 | 2/3/0 | 1/4/0 |
| MIXED | 75.90 | 71.38 | 2/3/0 | 0/5/0 |
| 합계 | — | — | 9/11/0 | 6/14/0 |

| Condition | v1.1 Local | Internet | DNS | TCP | HTTP |
|---|---:|---:|---:|---:|---:|
| NORMAL | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 |
| HIGH_LATENCY | 49.85 | 49.84 | 100.00 | 100.00 | 74.59 |
| PACKET_LOSS | 76.00 | 61.00 | 100.00 | 79.66 | 86.29 |
| MIXED | 32.64 | 58.51 | 100.00 | 92.79 | 83.36 |

Score 차이는 연속식 감점이 기존 경계 아래부터 조금씩 반영되고 구간 내부에서도 값에 비례하기 때문이다. RST 단독 감점 제거는 일부 점수를 올린다. Guard는 위 숫자 평균을 바꾸지 않고 Status만 보호한다. #35는 실측Ping Loss0%여서 v1.1도 NORMAL(96.41)이며 설정Loss 조건15건 모두를 탐지했다고 주장하지 않는다. 장애 설정 조건15건 중14건 Warning(93.3%)이고 NORMAL5건 모두Normal이지만, 표본이 적으므로 일반 성능 보장이나 개선 유의성 검정으로 해석하지 않는다.

CSV: `reports/health_score_v1_vs_v1_1.csv`, 실제20행. v1/v1.1 Score·Base/Final Status·5영역·Quality·Coverage·TCP sample·Guard·버전별Hash를 포함한다. 이전 실험/Health Score CSV는 덮어쓰지 않았다.

### 24.11 대표 Measurement 검증

| ID / Condition | v1 Overall·Status | v1.1 Overall | Base → Final | Local / Internet / DNS / TCP / HTTP |
|---|---|---:|---|---|
| 22 NORMAL | 100 NORMAL | 100.00 | NORMAL → NORMAL | 100 / 100 / 100 / 100 / 100 |
| 26 LATENCY | 72.50 WARNING | 72.39 | WARNING → WARNING | 49.855 / 49.855 / 100 / 100 / 74.7914 |
| 31 LOSS | 69.75 WARNING | 66.12 | WARNING → WARNING | 40 / 55 / 100 / 65.001 / 81.8459 |
| 36 MIXED | 71.75 WARNING | 66.68 | WARNING → WARNING | 14.4222 / 43.1776 / 100 / 100 / 90.0228 |
| 38 MIXED | 83 NORMAL | 78.73 | WARNING → WARNING | 14.7111 / 88.72 / 100 / 100 / 93.0287 |
| 34 LOSS | 81.75 NORMAL | 82.75 | NORMAL → WARNING | 100 / 55 / 100 / 69.999 / 100 |

- #22: 성능 감점 없음. DNS 부분 측정과 TCP27개 표본 한계는 유지한다.
- #26: Gateway/Internet RTT202.9ms가 각각50.145점, TTFB809.733ms가25.2086점 감점된다. 동일 지연의 관련 효과를 그룹으로 설명하되 여러 영역의 관측 품질은 모두 반영한다.
- #31: Gateway Loss20%−60, Internet Loss10%−45, TCP8.333%−34.999, TTFB690.465ms−18.1541. RST1은 별도 감점하지 않는다.
- #36: Gateway RTT105.778ms−40.5778+Loss10%−45, Internet RTT104.556ms−11.8224+Loss10%−45, TTFB559.636ms−9.9772. TCP0%는 재전송 감점이 없고 표본27개 제한만 표시한다.
- #38: Local14.7111은 낮지만 숫자 평균78.73을 강제로 더 낮추지 않는다. Local<40 및 기존 Rule warning의 Guard 근거를 표시한다.
- #34: Internet55와 TCP69.999의 감점은 남고 RST1 감점만 제거되어 Overall은81.75→82.75로 올랐다. **Base NORMAL이어도 Final WARNING**이므로 국소 장애 보호가 숫자 점수와 독립적으로 작동한다.

### 24.12 Regression Test

기존41개와 신규23개를 합친 **Backend64/64**가 Host Python3.13과 배포 이미지 Python3.12에서 모두 통과했다. 기존 API/Rule 테스트 파일을 바꾸지 않았다. Frontend **3/3** 및 Vite/Docker build 성공. 새 운영 라이브러리는 추가하지 않았다. Selenium은 `/tmp`의 별도 검증용 venv에만 설치했다. 기존 FastAPI/anyio deprecation3건과 JS551.12kB 청크 크기 경고는 남으며 기능 오류는 아니다. 별도 lint script는 기존에 없다.

| 검증 | 입력/방법 | 실제 결과 |
|---|---|---|
| Guard | Category<40+Overall>80, Rule warning+높은Score, Rule critical | 숫자 불변, Final 상태 보호 성공 |
| 선형 경계 | 6Metric 모든 anchor 직전/정확/직후, 단조/상한, Loss0 | 큰 점프 없음, 범위0~100 성공 |
| TCP/RST | 작은 표본, RST1, 반복RST 단독/지원 근거 | low_sample 표시, 정책별 감점 성공 |
| 결측/coverage | DNS partial, 전체 결측 Category, 가중치 재정규화 | null 안전 처리, Quality 분리 성공 |
| Hash | 숫자 표기/key 순서/정책 변경, v1 재로딩 | canonical 동일/실변경 다름, v1 Hash 유지 |
| DB/Backfill | 두 버전 공존, dry/apply/repeat/conflict, Rule 누락 | 기존 결과 보존, 재실행0INSERT, 충돌/누락 거부 |
| 실제 API | 두 버전의 실험20개 Score 상세와 History 대조 | 20/20 각각 일치, Agent 정확, 시간순 |
| 서비스/인증 | localhost/LAN health, Frontend, Swagger, 무인증API/Caddy | 200/200/200/200, 401/401 |
| 새 업로드/AI fallback | 격리 SQLite + 기존Agent JSON + Ollama unavailable | Rule/Score 먼저 저장, 기존 출력구조와 fallback 유지 |
| 실제 Ollama | #34 Score82.75/StatusWARNING/low_confidence, 비저장호출 | qwen3.5:4b-q4_K_M, available=true, warning/MEDIUM |
| 실제 Dashboard | 실제Agent6사례, v1/v1.1전환, 원인/범위/표본 표시 | Score/Status/Quality 및 근거 정상, JS 오류0 |
| 기존 UI | 개요/상세/AI/이력, 새로고침, 밝은 테마, 폭500px | 기존 기능 유지, 4탭 모두 문서 가로 넘침 없음 |

실제 Ollama 응답의 Primary Cause는 “관측된 문제: 외부 구간 패킷 손실, TCP 재전송 증가”, confidence MEDIUM이었다. measured_facts 집합은 실제기존값과 일치하며 모델 출력에 점수/상태 수정 필드는 없었다. 기존 AI 행을 재저장하지 않았다. JSONB key 순서 때문에 측정 사실의 순서가 달라질 수 있어 동일 내용은 집합으로 비교했다.

Frontend에는 버전 선택과 분리된 Score/Status/Quality, Cause Group, 선형 구간, TCP 표본, DNS coverage 설명을 추가했다. v1 선택 시에는 Guard가 없는 기존 점수 기준 상태임을 별도 문구로 명시한다. 실제 이력에는 점수1개+기존지표6개, 총7차트를 확인했다. 버전 전환은 #34 v1 81.75/NORMAL ↔ v1.1 82.75/WARNING으로 검증했다. 캡처는 `reports/screenshots/health-score-v1-1-{22,26,31,36,38,34}.png`이며 API 키 입력란을 숨겨 촬영했다. Agent의 오래된 last_seen을 ONLINE으로 오인 표시하지 않았다.

작업 재개 시 NetDoctor3컨테이너가 약21시간 중지돼 있었으므로 기존 컨테이너/DB볼륨을 안전하게 다시 시작한 뒤 Backend/Frontend만 빌드·교체했다. 검증 초기에는 운영 이미지에 테스트 디렉터리가 없어 pytest 경로 오류가 났고, 테스트를 임시 잘못된 위치에 복사했을 때 상대 YAML 경로 때문에 실패했다. 운영 코드를 바꾸지 않고 `/app/tests`에 검증용 테스트를 복사해64개 모두 통과했다. Selenium XPath는 React의 분리된 text node를 문자열 전체로 비교하도록 고쳐 화면 검증을 완료했다.

### 24.13 한계

Weight는 학습/통계 최적화 값이 아니며 그대로 유지했다. 선형 onset과 Guard floor는 설정 가능한 내부 품질 정책이지 절대 품질/SLA 기준이 아니다. 여전히 Category 간 상관 감점은 존재하고 Cause Group은 이를 설명할 뿐 인과적으로 제거하지 않는다. 모든 Metric을 연속식으로 바꾼 것은 아니며 Base/Final 상태의 구간형 판단도 남는다.

TCP low_sample은 수치/가중치를 그대로 두고 한계를 표시하는 방식이며 추정 신뢰구간이나 표본별 Weight 조정을 계산하지 않는다. 작은 캡처의 반복 RST 지원 조건도 인과 확증은 아니다. Cloudflare partial, #33/#34 DNS 누락, 실제0ms 출처 미검증, 조건당5회/Agent1대/netem interface 전체 적용/iperf3미사용의 기존 실험 한계는 그대로다. 이번 검증은 저장된 실제20건 기준이며 운영Agent의 새로운 v2.1업로드는 아직 실행하지 않았다. 신규 POST/AI fallback은 격리된 테스트 DB에서 검증했다. 외부 Caddy는401 보호를 확인했지만 로그인 후 외부 브라우저는 따로 검증하지 않았다. LAN 브라우저는 실제 배포로 검증했다.

### 24.14 결론

**Explainable Score + Local fault protection + Smooth deduction + Data quality indication**을 기존 구조 위에 추가했다. NORMAL100점은 유지했고, #34처럼 높은 평균에서 Rule/영역 장애가 묻히는 Status 문제를 보호했다. v1과v1.1 저장 결과/정책/CSV는 공존하며 원본20개 Measurement/Rule/AI/v1 Score의 전체 행은 해시로 보존을 확인했다. README와 비교CSV·캡처를 업데이트하고 실제 운영서비스/API/브라우저/Ollama 및 자동화 테스트를 검증했다.

다음 단계는 실제 Agent의 신규측정1회에서 v1.1 자동 저장을 확인하고, 표본 수/목적지/환경을 늘려 정책의 일반성을 평가하는 것이다. 검증20건에 맞춘 추가 Threshold 조정이나 기존 Rule/AI 재생성은 수행하지 않았다.

## 25. Bklit 기반 Dashboard 개편 (2026-09-28)

- 기존 React 19 + Vite 8 + JavaScript 단일 화면(개요·측정 상세·AI 진단·이력), `sessionStorage` API 키, `/api/v1` 상대 경로와 Nginx 3001 proxy를 확인하고 이 계약을 유지했다. Backend/Agent/DB 및 실험 원본 데이터는 수정하지 않았다.
- 공식 Bklit registry 방식으로 Line Chart, Area Chart, Y Axis와 필요한 의존성만 설치했다. shadcn JavaScript 설정(`tsx:false`), Tailwind v4와 Vite 플러그인, Bklit chart 관련 컴포넌트를 추가했다. 생성된 chart loading label의 잘못된 상대 import와 CSS `var(----chart-*)`를 수정해야 빌드가 통과했다.
- 신규 화면은 Rule severity 기반 상태 배지(임의 Health Score 없음), 7개 KPI, Internet/Gateway RTT·손실·DNS·TTFB·TCP 재전송 6개 차트, 실제 측정 목록, 구조화된 AI 진단으로 구성했다. 숫자·시간·ID 툴팁과 결측 제외 건수를 제공한다. `null`을 0으로 취급하지 않으며 실제 0은 그대로 표시한다. Agent online을 추측하지 않고 마지막 수신 시각과 5분 기준을 명시한다. Backend에 없는 실험 label은 만들지 않았다.
- 검증: `npm test` 1/1 통과(결측 DNS/실제 0% 손실/직전값 변화/Rule 상태), `npm run build` 성공, Docker `npm ci` 및 빌드 성공(의존성 감사 취약점 0건). Vite는 Bklit 포함 JS 약 542.50 kB에 대한 청크 크기 경고를 냈으나 기능 오류는 아니다. 별도 lint 스크립트는 원래 없어서 실행하지 않았다.
- 배포: `docker compose build frontend && docker compose up -d --no-deps frontend`; Backend와 PostgreSQL 컨테이너는 재생성하지 않았다. 배포 후 localhost/LAN의 3001 및 Backend `/health`는 HTTP 200. 외부 Caddy `/NetDoctorServer/`는 비인증 요청에 HTTP 401(기존 보호 유지)이며, Caddy 로그인 후 화면은 별도 재검증 필요하다.
- Headless Firefox에서 실제 Agent `IKEAWOLF-SERVER-C`의 최신 측정 #40, 6개 chart SVG, 4개 탭, AI 진단 표시와 오류 배너 없음 확인. 최근 50건 선택 시 실제 보유 31건 표시, 측정 #22 ID 링크 클릭→상세·AI 진단, 밝은 테마 전환, 새로고침이 모두 동작했다. 기존 22.17의 “브라우저 시각 캡처 미실시”는 **당시 상태**이며, 이번 개편 후 개요 브라우저 캡처를 `/tmp/netdoctor-dashboard-bklit.png`에 생성했다. 발표용 대표 #22·26·31·36 개별 시각 캡처는 아직 별도 확인이 필요하다.
