# 검증 명령과 완료 기준(DoD) — PTK_V2_BE

> 범위: **BE 전용**. 태그는 `README.md` 참고. 명령은 **레포 루트**에서 문서 그대로 실행한다 (`ai-operating-protocol.md` P-14).

## 1. 모든 PR 에서 필수

```bash
# (최초 1회) 가상환경
python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# 테스트 — API 키·MySQL 없이 실행된다 (tests/conftest.py 가 SQLite in-memory 와 빈 키로 격리)
PYTHONPATH=. pytest -v
```

- **V-1 [A 2026-11-27]** `pytest` 는 **실패 0건**이어야 한다. 2026-11-27 기준 결과: `6 passed`.
- **V-2 [D]** PR 의 `## 검증` 에는 실행한 명령과 **실제 출력의 요약(통과/실패 개수)** 을 그대로 적는다. 실행하지 않았으면 "미실행"이라고 쓴다.

## 2. 상황별 추가 검증 [D]

| 바꾼 것 | 추가로 할 일 |
|---|---|
| API(라우터·스키마) | `docs/openapi.json` 재생성 + `docs/API_SPEC.md` 갱신 (아래 명령). `git diff --stat docs/openapi.json` 이 **의도한 변경만** 포함하는지 확인 |
| 모델(DB 컬럼) | 컬럼 길이·NULL 변경은 MySQL(`utf8mb4`) 기준으로 검토하고 PR `그 외` 에 마이그레이션 영향 기록 (`alembic/versions/` 는 아직 비어 있음) |
| 덱 생성 로직 (`deck_blueprint.py` · `deck_synthesizer.py` · `research_query_planner.py` · `ppt_renderer/*`) | 100점 루브릭 **변경 전·후 점수**를 PR `검증` 에 기록 (`quality-rubric.md`). 총점이 **90점 미만이면 머지하지 않는다** [A 2026-11-27] |
| 외부 API 클라이언트 | 키가 하나도 없는 환경에서도 `pytest` 가 통과해야 한다 (`tests/conftest.py` 가 모든 키를 빈 값으로 덮어씀). 테스트에서 실제 외부 API 를 호출하지 않는다 |
| 버그 수정 | 실제 고객사/수치를 제외한 **익명화 기술 메모**만 PR `작업 내용`에 남긴다 (실측 로그는 로컬 전용 — `project-rules.md` BE-14) |

```bash
# OpenAPI 스냅샷 재생성 (2026-11-27 에 기존 docs/openapi.json 과 바이트 단위로 동일함을 확인한 명령)
PYTHONPATH=. python -c "import json; from app.main import app; print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))" > docs/openapi.json

# 서버 기동 스모크 (.env 필요 — environment.md)
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/health            # {"status":"ok", ...}

# 팩트북 100점 평가 (서버 실행 + 대상 프로젝트의 슬라이드·PPTX 필요)
python scripts/evaluate_factbook.py --project-id <프로젝트ID> --pptx <내보낸.pptx 경로> --api http://127.0.0.1:8000/api/v1
```

## 3. 완료 기준 (Definition of Done) [D]

PR 을 머지하기 전에 모두 만족해야 한다.

- [ ] `PYTHONPATH=. pytest -v` 실패 0건
- [ ] (해당 시) `docs/openapi.json` · `docs/API_SPEC.md` 갱신
- [ ] (해당 시) 100점 루브릭 전·후 점수 기록, 90점 이상
- [ ] 비밀값(`.env`·키·토큰)이 diff 에 없음 — `git diff --cached` 로 확인
- [ ] `git add` 는 파일 단위로 지정함 (`-A`/`.` 미사용)
- [ ] PR 본문 4개 섹션 + `Closes #N` 작성, `harness-check` 통과
- [ ] 머지 후 원격·로컬 브랜치 삭제 (`workflow.md` §2 의 7·8단계)

## 4. CI [D]

`.github/workflows/ci.yml` 이 PR 마다 `pip install -r requirements.txt` 와 `PYTHONPATH=. pytest -v` 를 실행한다. 로컬 검증과 같은 명령이므로 로컬에서 통과하지 못한 PR 을 올리지 않는다.
