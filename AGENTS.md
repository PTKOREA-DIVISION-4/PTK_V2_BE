# AGENTS.md — PTK_V2_BE (Factbook Generator Backend)

> 어떤 AI 도구(Claude · Gemini · GPT · Copilot · Cursor …)를 쓰든, 어떤 사람이 작업하든 **이 파일이 유일한 진입점**입니다.
> `CLAUDE.md` · `GEMINI.md` · `.github/copilot-instructions.md` 는 이 파일을 가리키는 포인터일 뿐입니다.

## 이 레포는

- FastAPI 기반 **팩트북 생성 백엔드**: 단일 브랜드·제품 리서치 수집(Perplexity · ScrapeCreators · Apify · Naver DataLab) → 기획자 검수 API → Claude 로 장표 합성 → 사전 QC → 16:9 PPTX 출력.
- 짝 레포: [`PTKOREA-DIVISION-4/PTK_V2_FE`](https://github.com/PTKOREA-DIVISION-4/PTK_V2_FE) (Next.js 프런트엔드). FE 는 이 레포의 `docs/API_SPEC.md` 를 기준으로 설계됩니다.
- 이 레포와 FE 레포는 **PUBLIC** 입니다. 비밀값을 절대 올리지 않습니다.

## 먼저 읽을 것 (순서 고정, 끝까지)

1. `docs/harness/README.md` — 인덱스·태그·우선순위
2. `docs/harness/ai-operating-protocol.md` — 행동 규약 (공통)
3. `docs/harness/workflow.md` — 이슈 · 브랜치 · 커밋 · PR · 머지 · 브랜치 정리 (공통)
4. `docs/harness/project-rules.md` — 사용자가 지시한 BE 규칙
5. `docs/harness/architecture.md` — 계층 · 폴더 · 규약
6. `docs/harness/verification.md` — 실행할 검증 명령과 완료 기준
7. `docs/harness/environment.md` — 버전 · 설치 · 환경변수
8. `docs/harness/quality-rubric.md` — 팩트북 100점 품질 루브릭
9. `docs/harness/rule-changes.md` — 규칙을 추가·변경하는 절차

## 절대 규칙 (요약 — 근거와 상세는 위 문서)

1. **[U]** 모든 작업은 **이슈 → 브랜치 → 커밋 → PR** 로만 한다. `main` 직접 push 금지.
2. **[U]** PR 에는 `Closes #N` · `## 작업 내용` · `## 수정 파일` · `## 검증` · `## 그 외` 를 적는다 (자동 검사: `harness-check`).
3. **[U]** 브랜치명은 `<type>/<이슈번호>` (예: `feat/12`). 콜론(`:`)은 git 에서 쓸 수 없어 슬래시로 확정했다.
4. **[U]** 머지가 끝난 브랜치는 **원격·로컬 모두 삭제**한다.
5. **[U]** 두 레포는 PUBLIC 이지만 사내 서비스이므로 API 키·토큰·`.env` 뿐 아니라 **고객사명·실측 수치·원본 산출물·내부 URL 등 기밀 정보도 절대 커밋 금지** (`P-11`).
6. **[A]** 수집하지 못한 수치는 **지어내지 않고 `확인 못 함`** 으로 표기한다 (환각 0 원칙).
7. **[A]** 변경 후 `PYTHONPATH=. pytest -v` 를 통과시킨다. 덱 생성 로직을 바꾸면 100점 루브릭(목표 90점 이상)도 돌린다.
8. **[U]** 백엔드 로직을 지저분하게 만들지 않는다. 구현 전에 **더 좋은 방향이 있는지 먼저 검토**하고 PR `그 외` 에 한 줄 남긴다.
9. **[U]** 새 규칙은 **사용자에게 먼저 물어보고** 승인된 것만 추가한다 (`docs/harness/rule-changes.md`).

## 명령 치트시트

```bash
# 설치 (최초 1회)
python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# 테스트 (키·MySQL 없이 실행됨)
PYTHONPATH=. pytest -v

# 서버 (docs/harness/environment.md 에서 .env 준비 후)
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000   # Swagger: /docs, 헬스: /health

# OpenAPI 스냅샷 재생성 (API 를 바꿨을 때)
PYTHONPATH=. python -c "import json; from app.main import app; print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))" > docs/openapi.json
```

## 하지 말 것

- `git add -A` / `git add .` (파일을 하나씩 지정), `main` force push, 승인 없는 레포 설정 변경.
- `.env` · API 키 · 토큰을 코드·문서·PR·로그에 노출.
- 요청하지 않은 리팩터링·의존성 추가·범위 확장.
- 실행하지 않은 검증을 했다고 보고.
- 승인받지 않은 규칙을 하네스에 기록.
