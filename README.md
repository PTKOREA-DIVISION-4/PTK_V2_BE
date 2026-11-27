# PTK_V2_BE — Factbook Generator Backend

제안서 작성 전 사전 리서치 보고서(팩트북)를 만들기 위해 여러 사람이 오래 걸리던 **조사 · 정리 · 장표화**를 AI 와 데이터 수집 파이프라인으로 가속하는 서비스의 **백엔드**입니다. 기획자가 중간 단계에서 팩트를 검증하고 방향을 잡을 수 있도록 검수 API 를 제공합니다.

- 프런트엔드: [`PTKOREA-DIVISION-4/PTK_V2_FE`](https://github.com/PTKOREA-DIVISION-4/PTK_V2_FE) (Next.js)
- **작업 규칙은 [`AGENTS.md`](./AGENTS.md) 와 [`docs/harness/`](./docs/harness/README.md) 에 있습니다.** 사람이든 AI 든 작업 전에 먼저 읽어 주세요.

## 무엇을 하나

1. **수집** — Perplexity(시장·경쟁 리서치) · ScrapeCreators/Apify(SNS·커뮤니티) · Naver DataLab(검색·쇼핑 점유율)을 비동기 Job 으로 병렬 수집
2. **검수** — 자료 채택/제외, 근거 문장, 기획자 코멘트 윤문 API
3. **합성** — Claude 로 표준 목차(0 개요 → 1 자사 → 2 시장 → 3 경쟁사 → 4 소비자 → 5 요약·결론) 장표 초안 생성
4. **사전 QC** — 누락·빈 장표를 막는 게이트
5. **출력** — 16:9 PPTX 생성·다운로드

## 빠른 시작

```bash
docker compose up -d mysql                       # MySQL 8.0 (로컬 개발용)
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                             # .env 에 API 키 입력 (절대 커밋 금지)
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- Swagger UI: http://127.0.0.1:8000/docs · 헬스체크: `/health`
- API 명세(FE 설계 기준서): [`docs/API_SPEC.md`](./docs/API_SPEC.md) · OpenAPI 스냅샷: [`docs/openapi.json`](./docs/openapi.json)
- 테스트: `PYTHONPATH=. pytest -v` (키·MySQL 없이 실행)
- 자세한 환경·검증 절차: [`docs/harness/environment.md`](./docs/harness/environment.md) · [`docs/harness/verification.md`](./docs/harness/verification.md)

## 문서

| 문서 | 내용 |
|---|---|
| [`docs/harness/`](./docs/harness/README.md) | 작업 규약(하네스): 워크플로우 · 프로젝트 규칙 · 아키텍처 · 검증 · 품질 루브릭 |
| [`docs/API_SPEC.md`](./docs/API_SPEC.md) | 화면별 엔드포인트·상태 전이·에러 규약 |
