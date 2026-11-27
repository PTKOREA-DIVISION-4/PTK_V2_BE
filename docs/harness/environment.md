# 환경 — PTK_V2_BE

> 범위: **BE 전용**. 태그는 `README.md` 참고. 값이 있는 비밀(키·토큰)은 이 문서에 **적지 않는다.**

## 1. 버전 [D]

| 항목 | 버전 | 근거 |
|---|---|---|
| Python | **3.12** (개발 환경 3.12.15) | `.venv` 의 `python --version` |
| MySQL | **8.0** (`utf8mb4`, 타임존 `+09:00`) | `docker-compose.yml` |
| 패키지 | `requirements.txt` 의 범위 지정 그대로 | FastAPI · SQLAlchemy 2.0 · Pydantic v2 · python-pptx · matplotlib 등 |

## 2. 설치·실행 절차 [D]

```bash
# 1) MySQL (Docker) — 로컬 개발 전용 기본 계정이 들어 있다 (운영에서 사용 금지)
docker compose up -d mysql

# 2) 가상환경 + 의존성
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3) 환경변수
cp .env.example .env        # 그리고 .env 에 키를 채운다. .env 는 절대 커밋하지 않는다

# 4) 서버 (기본 포트 8000)
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
#   Swagger UI : http://127.0.0.1:8000/docs
#   OpenAPI    : docs/openapi.json
#   API 명세   : docs/API_SPEC.md

# 5) 테스트 (키·MySQL 불필요)
PYTHONPATH=. pytest -v
```

- **ENV-1 [D]** 기본 포트는 **8000** 이다. 이미 다른 프로세스가 8000 을 쓰고 있으면 그 프로세스를 끄지 말고 **다른 포트**(예: 8001)로 띄운 뒤, FE 의 `NEXT_PUBLIC_API_BASE_URL` 을 같은 포트로 맞추고 PR/보고에 적는다 (`ai-operating-protocol.md` P-13).
- **ENV-2 [A 2026-11-27]** 키는 `.env` 에만 둔다. `.env` 는 `.gitignore` 로 제외돼 있고, `.env.example` 에는 **빈 값만** 둔다.

## 3. 환경변수 (`.env.example` 기준 이름만)

| 구분 | 이름 |
|---|---|
| 앱 | `APP_NAME` · `APP_ENV` · `DEBUG` · `API_V1_PREFIX` · `CORS_ORIGINS` |
| DB | `DATABASE_URL` · `DATABASE_SYNC_URL` · `DB_AUTO_CREATE_TABLES` |
| 외부 API 키 | `PERPLEXITY_API_KEY` · `ANTHROPIC_API_KEY` · `SCRAPECREATORS_API_KEY` · `APIFY_API_TOKEN` · `X_NCP_APIGW_API_KEY_ID` · `X_NCP_APIGW_API_KEY` |
| 엔드포인트·모델 | `PERPLEXITY_BASE_URL` · `PERPLEXITY_MODEL` · `ANTHROPIC_BASE_URL` · `ANTHROPIC_MODEL` · `SCRAPECREATORS_BASE_URL` · `APIFY_BASE_URL` · `NAVER_APIGW_BASE_URL` · `DEFAULT_NAVER_SHOPPING_CATEGORY_ID` |
| 동시성·캐시·저장 | `STORAGE_ROOT` · `CACHE_TTL_SECONDS` · `HTTP_TIMEOUT_SECONDS` · `MAX_CONCURRENT_PERPLEXITY` · `MAX_CONCURRENT_NAVER` · `MAX_CONCURRENT_SCRAPECREATORS` · `MAX_CONCURRENT_APIFY` · `MAX_CONCURRENT_ANTHROPIC` |

- 새 환경변수를 추가하면 **같은 PR 에서** `app/core/config.py` · `.env.example` · 이 표를 함께 고친다 (`ai-operating-protocol.md` P-8).

## 4. 런타임 산출물

`storage/cache` · `storage/exports` · `storage/media` 는 실행 중 생기는 산출물이라 git 에서 제외한다 (`.gitkeep` 만 추적). `*.db` · `*.sqlite3` · `.pytest_cache/` 도 제외한다.
