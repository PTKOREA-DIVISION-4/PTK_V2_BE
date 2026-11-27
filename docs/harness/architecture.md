# 아키텍처 — PTK_V2_BE

> 범위: **BE 전용**. 태그는 `README.md` 참고. 태그가 없는 문장은 코드에서 관측한 현재 상태다.

## 1. 계층 구조 [U 2026-11-25]

백엔드는 FastAPI 를 기반으로 **Controller · Service · Repository · Entity · DTO** 계층이 명확히 분리된 **레이어드 아키텍처**다.

| 계층 | 폴더 | 책임 |
|---|---|---|
| 진입점 | `app/main.py` | 앱 생성, 전역 예외 처리(`AppException`, `RequestValidationError`), 라우터 등록, `/health`, `/media` 정적 서빙 |
| Core | `app/core/` | 환경변수(`config.py`) · DB 연결(`database.py`) · 비동기 작업 관리(`job_manager.py`) · 캐시(`cache.py`) · 예외(`exceptions.py`) |
| Controller | `app/api/routers/` | HTTP 요청/응답만 담당. 기능 단위로 라우터 분리: `projects` · `research_plans` · `collections` · `reviews` · `exports` · `jobs` |
| Service | `app/services/` | 비즈니스 로직: 단일 브랜드·제품 기준 수집 오케스트레이션, 산업군 분기, SNS TOP 5 추출, Claude 구조화·근거 추출·윤문·요약, QC, PPTX 생성 |
| Integration | `app/integrations/` | 외부 API/크롤러 클라이언트(Perplexity · Naver DataLab · ScrapeCreators · Apify · Anthropic · 미디어 다운로더). Service 가 외부 연동 세부 구현에 얽매이지 않게 분리 |
| Repository | `app/repositories/` | 데이터 저장·조회 |
| Entity | `app/models/` | DB·도메인 모델 (SQLAlchemy 2.0) |
| DTO | `app/schemas/` | API 요청·응답 및 계층 간 전달 스키마 (Pydantic v2) |

- **AR-1 [U 2026-11-25]** 위 계층 책임을 섞지 않는다. DB/도메인 모델은 `models`, 요청·응답·계층 간 전달은 `schemas` 로 **구분**한다.
- **AR-2 [D]** 의존 방향은 `routers → services → repositories → models` 이고, `integrations` 는 `services` 에서만 호출한다. 역방향 import(예: repository 가 service 를 import)는 하지 않는다.
- **AR-3 [D]** 라우터에는 비즈니스 로직을 넣지 않는다. 서비스는 FastAPI 의 `Request`/`Response` 에 의존하지 않는다. 리포지토리에는 DB 접근 코드만 둔다.
- **AR-4 [D]** 새 외부 API 는 `integrations/` 에 클라이언트 클래스를 추가하고 `base_client.py` 의 공통 동작(재시도·타임아웃)을 재사용한다.

## 2. 현재 폴더 구조 (관측)

```
app/
├─ main.py
├─ core/            config.py · database.py · job_manager.py · cache.py · exceptions.py
├─ api/
│  ├─ deps.py
│  └─ routers/      projects · research_plans · collections · reviews · exports · jobs
├─ services/
│  ├─ collection_orchestrator.py     # 병렬 수집 총괄
│  ├─ research_query_planner.py      # Perplexity 리서치 쿼리 계획(8개 동시)
│  ├─ datalab_metrics_service.py     # 검색 점유율(SoS)·증감 계산
│  ├─ sns_ranking_service.py         # SNS TOP 5
│  ├─ project_service.py · research_plan_service.py · review_service.py
│  ├─ deck_blueprint.py              # 결정론적 덱 골격 + 문장 정리·길이 보호(sanitize)
│  ├─ deck_synthesizer.py            # Claude 합성(5개 배치 동시 호출)
│  ├─ llm_structuring_service.py     # 수집 원문 → 팩트 추출·슬라이드 초안 생성 (deck_blueprint / deck_synthesizer 호출)
│  ├─ qc_service.py                  # 사전 QC 게이트
│  ├─ ppt_export_service.py          # 출력 서비스
│  └─ ppt_renderer/                  # theme · chart_builder · media_layout · slide_builders · renderer
├─ integrations/    base_client · perplexity · anthropic · apify · naver_datalab · scrapecreators · media_downloader
├─ repositories/    project · research_plan · source_item · fact_item · slide_draft · export · job
├─ models/          base · project · research_plan · collection · factbook · job
└─ schemas/         common · project · research_plan · collection · review · qc · export · job
alembic/            마이그레이션 환경 (versions/ 는 아직 비어 있음)
docs/               API_SPEC.md · openapi.json · harness/  (고객사 포함 로그는 로컬 전용, 레포 제외)
scripts/            evaluate_factbook.py  (100점 품질 평가)
storage/            cache · exports · media  (런타임 산출물, git 제외 — .gitkeep 만 추적)
tests/              conftest.py · test_api_e2e.py · test_datalab_and_sns.py · test_qc_and_ppt.py
```

## 3. 코드 규약 (관측 → 규칙화) [D]

- Python **3.12**, 모든 모듈 상단에 `from __future__ import annotations`.
- SQLAlchemy **2.0 비동기**(`aiomysql` 운영 · `aiosqlite` 테스트), Pydantic **v2** + `pydantic-settings`.
- 모든 API 는 `API_V1_PREFIX`(기본 `/api/v1`) 아래에 둔다. 헬스체크 `/health`, 정적 미디어 `/media/{project_id}/{파일}`.
- 에러는 `AppException` → **`ErrorEnvelope`**(`error.code / message / user_action_hint / details / retryable`) 로 통일한다. 새 에러 코드는 `docs/API_SPEC.md` §1.2 에 추가한다.
- 모든 설정은 `app/core/config.py` 의 `Settings` 로만 읽는다. `os.environ` 직접 접근은 하지 않는다 (테스트는 `conftest.py` 가 환경을 격리).
- 슬라이드 텍스트는 DB 컬럼 길이(MySQL `VARCHAR`)를 넘지 않게 `sanitize_slide_draft` 를 거친다.

## 4. 팩트북 생성 파이프라인 (관측)

1. `research_query_planner` — Perplexity 리서치 쿼리 8개를 동시에 실행 (자사 2 · 시장 2 · 경쟁사 2 · 소비자 2 등 섹션별 분산).
2. `collection_orchestrator` — SNS · 커뮤니티 · DataLab 수집을 병렬 Job 으로 실행하고 `JobManager` 로 진행률을 관리.
3. `deck_blueprint.build_deterministic_deck` — 표준 목차 22장 골격을 **결정론적으로** 만든다 (Claude 실패 시에도 빈 덱이 나오지 않게 하는 안전망).
4. `deck_synthesizer.synthesize_deck` — Claude 를 **5개 배치**(개요·자사 / 시장 / 경쟁사 / 소비자 / 요약·결론)로 동시에 호출해 골격을 덮어쓴다. 한 배치가 실패해도 해당 슬라이드는 결정론 골격으로 남는다.
5. `qc_service` 사전 QC → `ppt_export_service` / `ppt_renderer` 로 PPTX 생성.

- **AR-5 [D]** 한 번의 Claude 호출에 담는 슬라이드 블록은 **6개 이하**로 유지한다. (9블록 배치가 JSON 길이 9천 자 근처에서 파싱 실패한 사례 반영)
- **AR-6 [D]** Claude 에 넘기는 프롬프트에는 "JSON 문자열 값 안에서 큰따옴표 대신 작은따옴표를 쓴다"는 지시를 포함한다.
