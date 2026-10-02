# NetDoctor v2 Health Score 설계 — 2026-10-03

구현 전 확정한 정책이다. ID21~40의 점수를 보고 임계값을 사후 조정하지 않는다.

- v1: 첫 커밋 `32a08f5`, `v1.0-mvp` 태그. 작업 브랜치 `feature/health-score`. DB SQL 백업은 Git 제외·권한 600.
- 별도 YAML `backend/app/health_score.yaml`, 순수 Score Engine, Pydantic 검증. 기존 Rule Engine/Agent schema는 유지한다.
- 가중치: Local .20 / Internet .25 / DNS .15 / TCP .20 / HTTP .20. 도달성과 전송 품질에 .65, DNS .15, HTTP .20을 배정한다. 실험 환경 전체 품질의 설명 지표이며 공식 SLA 지표가 아니다.
- 각 영역 100에서 구간 감점. 첫 주요 RTT/Loss/DNS/재전송/TTFB 경계는 기존 Rule 기준과 일치한다. Internet RTT>150 / Gateway RTT>20 / Loss>=3 / DNS>300 / TCP>=5 / TTFB>800. TCP 1~5%는 정상 범위 안의 소폭(10점) 품질 감점.
- Local RTT: >20 -25, >100 -40, >200 -50, >500 -65. Internet RTT: >150 -30, >200 -50, >500 -65. 양 방향 손실: >=3 -25, >=5 -35, >=10 -45, >=20 -60, >=50 -75, >=100 -100.
- DNS 응답: >300 -25, >600 -40, >1500 -60. DNS 서버별 감점은 최대 1개만 적용하며, 일부 직접 질의 실패는 성능 감점으로 환산하지 않는다.
- TCP 재전송: >=1 -10, >=5 -25, >=10 -40, >=20 -60, >=50 -80, >=100 -100. Duplicate ACK>=3 -10 / >=10 -25는 재전송과 같은 그룹에서 최대 1개. RST>=1 -10 / >=5 -25, Zero Window>=1 -15 / >=5 -30. TCP 표본 50 미만은 partial/low_sample이며 그 자체로 감점하지 않는다.
- HTTP status>=400 -30 / >=500 -60. TTFB>800 -25 / >1500 -40 / >3000 -60. total>2000 -25 / >4000 -40 / >8000 -60; connect>500 -20 / >1500 -35; TLS>1000 -20 / >3000 -35. 시간 값들은 하나의 timing 그룹에서 최대 감점만 적용한다. 높은 TTFB는 원격 서버 자체 장애를 증명하지 않는다.
- loss=100%는 그 방향의 RTT 추가 감점 없이 0점. 합계 100을 넘으면 실제 적용 감점을 제한해 `100−Σpoints=score`를 보장한다.
- Score severity: >=80 normal / >=60 warning / <60 critical. 기존 Rule severity와 별개 필드/라벨로 표시한다. 가중 평균은 단일 규칙 경보와 항상 같지 않다.
- 결측/비유한/음수/범위 위반은 점수 입력에서 제외한다. 영역에서 품질 지표가 전혀 없으면 score=null. Coverage는 설정 품질 지표 중 유효 비율. unavailable 영역은 제외하여 나머지 가중치를 정규화하되, 원래 가중치 합 .50 이상에서만 Overall을 제공한다. Overall coverage는 누락 포함 원래 가중치로 계산한다.
- 링크/인터페이스 상태는 v1 Measurement에 없어 추정하지 않는다. Traceroute timeout/hop 수만으로 장애 감점하지 않는다. Collector 오류는 성능과 구별해 notes에 남긴다.
- `health_scores`: Measurement FK + score_version unique, overall score/severity, 결과 JSONB, YAML snapshot/hash, created_at. config 변경 시 version을 바꾼다. 기존 버전 결과는 덮어쓰지 않는다.
- 신규 업로드 시 Rule→Score 저장→AI. 기존 API에는 optional health_score 추가, 별도 GET `/api/v1/measurements/{id}/health-score`. 기존 History가 점수를 함께 반환한다. AI에는 읽기 전용 점수 근거만 전달한다.
- Backfill은 기본 dry-run, 명시적 `--apply`에서만 신규 Score INSERT. 범위/Agent 검증·중복 방지·동일 버전 config conflict 검사. 원본 Measurement/Rule/AI는 수정하지 않는다.
- 검증: 기존15개, 범위·가중치·4조건·결측·partial·감점합·API·persist·backfill·History·AI read-only·브라우저 확인. 실제20건 원본 hash 비교. CSV 3개(개별/조건평균/대표4건)를 만든다.
