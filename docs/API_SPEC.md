# PTKOREA Factbook Generator — 백엔드 API 명세서 (Frontend UI/UX 설계 기준서)

> **문서 목적**: 프론트엔드 UI/UX 디자이너 및 Next.js 개발자가 복잡한 리서치·검수·시사점·출력 화면을 직관적으로 설계하고 바로 연동할 수 있도록, 5단계 워크플로우 화면별 엔드포인트, 상태 전이, UI 가이드 필드, 에러 처리 규약 및 실제 JSON 예시를 정리한 공식 API 명세서입니다.
>
> - **Base URL (Local)**: `http://localhost:8000`
> - **API Prefix**: `/api/v1`
> - **정적 미디어 미리보기**: `GET /media/{project_id}/{filename}` (로컬 아카이빙된 SNS 썸네일·차트·캡처 이미지)
> - **Swagger UI**: `GET /docs` | **OpenAPI JSON**: `backend/docs/openapi.json`

---

## 1. 프론트엔드 공통 규약 & UX 방어 원칙

### 1.1 멱등성 & 중복 클릭 방어 (`Idempotency-Key`)
- `POST /collections/run`, `POST /collections/retry` 등 비동기 작업 생성 API 호출 시 프론트엔드는 요청마다 UUID 기반 `Idempotency-Key` 헤더를 생성해 전송합니다.
- 네트워크 순단으로 재시도하더라도 동일한 `Idempotency-Key`가 오면 백엔드가 중복 Job을 띄우지 않고 기존 `JobStatusResponse`를 반환합니다.

### 1.2 표준 에러 응답 (`ErrorEnvelope`) 및 UI 액션 매핑
모든 4xx/5xx 에러는 아래 고정 구조로 반환되므로 프론트엔드는 별도 분기 없이 토스트/모달에 `message`와 `user_action_hint`를 노출하면 됩니다.

```json
{
  "error": {
    "code": "QC_BLOCKED",
    "message": "사전 품질 검증(QC)에서 차단 항목(BLOCKER)이 발견되어 PPTX를 생성할 수 없습니다.",
    "user_action_hint": "차단 사유를 확인하고 누락된 장표나 근거를 보완해 주세요.",
    "details": [
      {
        "gate_code": "REQUIRED_SECTIONS",
        "severity": "BLOCKER",
        "message": "필수 목차 섹션이 누락되어 출력할 수 없습니다: 4_CONSUMER",
        "target_section": "4_CONSUMER",
        "target_slide_id": null,
        "user_action_hint": "누락된 섹션을 포함하여 장표 초안을 다시 생성해 주세요."
      }
    ],
    "retryable": false
  }
}
```

| 에러 코드 (`code`) | HTTP | `retryable` | 프론트엔드 권장 UX 처리 |
| :--- | :---: | :---: | :--- |
| `REQUEST_VALIDATION_ERROR` | 422 | `false` | 폼 필드 하단 인라인 유효성 메시지 표시 |
| `RESOURCE_NOT_FOUND` | 404 | `false` | 안내 모달 후 프로젝트 대시보드(`/`)로 이동 유도 |
| `JOB_ALREADY_RUNNING` | 409 | `false` | `details[0].active_job_id`로 진행률 폴링 즉시 재연결 |
| `QC_BLOCKED` | 400 | `false` | `details`의 `target_section` / `target_slide_id`로 "바로 보완하기" 링크 제공 |
| `EXTERNAL_API_ERROR` | 502 | `true` | 에러 배너 + `[선택 소스 재시도]` 버튼 활성화 |

### 1.3 공통 워크플로우 네비게이션 배지 (`workflow_meta`)
`GET /api/v1/projects/{project_id}/summary` 및 `research-plan` 응답에 포함되는 `workflow_meta`로 상단 스텝 네비게이션 배지와 **"이번 단계에서 결정할 일"** 안내 문구를 그대로 렌더링합니다.

```json
{
  "current_stage": "COLLECT",
  "plan_confirmed": true,
  "total_sources_count": 48,
  "pending_sources_count": 12,
  "approved_sources_count": 30,
  "rejected_sources_count": 6,
  "total_slides_count": 9,
  "unreviewed_slides_count": 4,
  "missing_sections": [],
  "can_export": true,
  "next_step_hint": "미검토 장표 4건을 확인하고 기획자 코멘트를 반영해 주세요."
}
```

---

## 2. 워크플로우 5단계 화면별 API 상세 명세

### Step 0. 프로젝트 설정 (`/projects/new`, `project-setup`)
> **핵심 UX**: 단일 브랜드 × 단일 주력 제품 원칙 강제, 산업군 선택 시 분석 트랙(`REVIEW_CENTRIC` vs `MARKET_CENTRIC`) 자동 분기, SNS URL 플랫폼 자동 감지.

#### 1) 키워드·해시태그 & 트랙 AI 추천
- `POST /api/v1/projects/recommend-keywords`
- **Request**:
```json
{
  "brand_name": "설화수",
  "product_name": "윤조에센스 6세대",
  "industry_category": "뷰티/화장품",
  "competitor_brands": ["라네즈", "헤라"]
}
```
- **Response (`200 OK`)**: `recommended_groups` (OWN / COMPETITOR / INDUSTRY 3종), `suggested_naver_shopping_category_id` (`"50000002"`), `suggested_analysis_track` (`"REVIEW_CENTRIC"`).

#### 2) 새 프로젝트 생성
- `POST /api/v1/projects`
- **Request**:
```json
{
  "name": "2026 하반기 설화수 윤조에센스 팩트북",
  "brand_name": "설화수",
  "product_name": "윤조에센스 6세대",
  "industry_category": "뷰티/화장품",
  "period_start": "2026-06-01",
  "period_end": "2026-11-25",
  "competitors": [
    { "brand_name": "라네즈", "product_name": "워터뱅크 크림" },
    { "brand_name": "헤라", "product_name": "시그니아 세럼" }
  ],
  "sns_accounts": [
    {
      "owner_type": "OWN",
      "brand_label": "설화수",
      "account_url": "https://www.instagram.com/sulwhasoo.official/"
    },
    {
      "owner_type": "COMPETITOR",
      "brand_label": "라네즈",
      "account_url": "https://www.instagram.com/laneige_kr/"
    }
  ],
  "keyword_groups": [
    {
      "group_type": "OWN",
      "label": "설화수 윤조에센스",
      "keywords": ["설화수", "윤조에센스", "윤조에센스 6세대"],
      "hashtags": ["#설화수", "#윤조에센스"]
    }
  ]
}
```
- **Response (`201 Created`)**: 생성된 `ProjectResponse` (`id`, 자동 분기된 `analysis_track`, 자동 추출된 SNS `platform`/`handle`, 초기 `current_stage: "PLAN"`).

#### 3) 기타 프로젝트 관리 API
- `GET /api/v1/projects`: 전체 프로젝트 목록
- `GET /api/v1/projects/{project_id}`: 상세 설정
- `GET /api/v1/projects/{project_id}/summary`: 프로젝트 + `workflow_meta` + `api_readiness` (각 API 키 준비 여부 boolean)
- `PATCH /api/v1/projects/{project_id}`: 설정 수정
- `DELETE /api/v1/projects/{project_id}`: 삭제

---

### Step 1. 조사 계획 (`/projects/[id]/plan`, `research-plan`)
> **핵심 UX**: 0~5장 목차별 조사 항목 On/Off 토글, 수집 커뮤니티 선택(`dcinside`, `fmkorea`, `theqoo`, `clien`, `naver_blog`, `naver_cafe`), 데이터랩 비교 그룹 미리보기 확인 후 확정.

#### 1) 조사 계획 조회
- `GET /api/v1/projects/{project_id}/research-plan`
- **Response (`200 OK`)**: `analysis_track`, `is_confirmed`, `target_communities`, `datalab_groups_config`, `estimated_duration_seconds`, `items` (`0_OVERVIEW`..`5_SUMMARY_CONCLUSION`별 항목 목록), `workflow_meta`.

#### 2) 조사 계획 확정 저장
- `PUT /api/v1/projects/{project_id}/research-plan`
- **Request**:
```json
{
  "is_confirmed": true,
  "target_communities": ["theqoo", "dcinside", "fmkorea", "naver_blog", "naver_cafe"],
  "items": [
    { "item_key": "own_sns_top5_and_collab", "is_enabled": true },
    { "item_key": "consumer_voc_and_kbf", "is_enabled": true }
  ]
}
```

---

### Step 2. 자료 수집 & 일괄 검수 (`/projects/[id]/collect`, `data-collection`)
> **핵심 UX**: 비동기 진행률 모니터링(폴링/SSE) + 실패 소스만 선택 재시도 + 수집 인덱스 테이블에서 **일괄 채택/제외** + 슬라이드오버 원문 뷰어(`highlight_spans` 형광펜 표시).

#### 1) 다중 소스 비동기 수집 시작 & 부분 재시도
- `POST /api/v1/projects/{project_id}/collections/run` (`Header: Idempotency-Key`)
  - Body (선택): `{ "force_refresh": false, "selected_sources": null }`
  - Response (`202 Accepted`): `JobStatusResponse` (`id: job_id`, `subtasks` 6개: `perplexity_research`, `naver_datalab`, `sns_official_top5`, `creator_collab`, `community_voc`, `media_archiving`).
- `POST /api/v1/projects/{project_id}/collections/retry`
  - Body: `{ "subtask_keys": ["community_voc"], "force_refresh": true }`

#### 2) 작업 진행률 폴링 / SSE 스트리밍 / 취소
- `GET /api/v1/jobs/{job_id}` (2초 간격 폴링 권장)
- `GET /api/v1/jobs/{job_id}/stream` (실시간 `text/event-stream` SSE 지원)
- `POST /api/v1/jobs/{job_id}/cancel`
- **Job 상태 Enum**: `PENDING` | `RUNNING` | `PARTIAL_SUCCESS` (일부 소스 실패, 나머지 확인 가능) | `COMPLETED` | `FAILED` | `CANCELLED`.

#### 3) 수집 인덱스 테이블 + 필터별 카운트(`facets`) 조회
- `GET /api/v1/projects/{project_id}/sources?section_code=4_CONSUMER&channel=theqoo&review_status=PENDING&q=보습&page=1&page_size=30`
- **Response (`200 OK`)**: `items` (`SourceItemSummary[]`), `facets` (탭/필터 칩 숫자 배지용 `by_review_status`, `by_section`, `by_channel`, `by_provider`), `total`.

#### 4) 수집 원문 전문 & 형광펜 하이라이트 상세 조회 (슬라이드오버용)
- `GET /api/v1/projects/{project_id}/sources/{source_id}`
- **Response (`200 OK`)**:
```json
{
  "id": "src_001",
  "section_code": "4_CONSUMER",
  "provider": "APIFY",
  "channel": "theqoo",
  "title": "윤조에센스 6세대 한 달 실사용 솔직 후기",
  "content": "건조한 환절기에 첫 단계로 쓰면 속건조가 확실히 잡혀요. 향도 은은해서 재구매 의사 있습니다.",
  "evidence_quote": "건조한 환절기에 첫 단계로 쓰면 속건조가 확실히 잡혀요.",
  "highlight_spans": [
    { "start": 0, "end": 34, "quote": "건조한 환절기에 첫 단계로 쓰면 속건조가 확실히 잡혀요." }
  ],
  "review_status": "PENDING",
  "media_assets": []
}
```
> **UI 팁**: `content` 문자열에서 `highlight_spans[i].start` ~ `end` 구간을 `<mark>` 태그로 강조하면 LLM이 추출한 근거 문장이 원문 어디에 있는지 기획자가 1초 만에 검증할 수 있습니다.

#### 5) 일괄 채택 / 일괄 제외 (Bulk Action)
- `PATCH /api/v1/projects/{project_id}/sources/bulk`
- **Request**:
```json
{
  "source_ids": ["src_001", "src_002", "src_003"],
  "review_status": "APPROVED",
  "filter_all_matching": false
}
```
  *(현재 필터에 걸린 전체 항목을 한 번에 채택하려면 `filter_all_matching: true`, `filter_section`/`filter_channel` 전달)*

#### 6) 정량 데이터랩 & SNS TOP 5 전용 뷰 조회
- `GET /api/v1/projects/{project_id}/datalab`: 검색어 트렌드·쇼핑 인사이트 시계열, **검색 점유율(`share_of_search_pct`)**, 증감률, 피크 시점, **`methodology_note`**.
- `GET /api/v1/projects/{project_id}/sns-top5`: 기간 필터링된 `own_top_posts`, `competitor_top_posts`, `creator_collabs` 및 로컬 아카이빙된 `media_asset` 정보.

---

### Step 3. 검토·시사점 & 코멘트 윤문 (`/projects/[id]/review`, `fact-review`)
> **핵심 UX**: `0~5장` 슬라이드 카드 목록 검토, 기획자 코멘트 입력 후 **AI 윤문 전/후 Diff 비교 카드** 확인 뒤 `[반영]`/`[원복]`, 현황 요약 **2장 vs 4장 분할 모드 전환**, 섹션 일괄 검토 완료.

#### 1) 0~5장 장표 초안 생성 & 조회
- `POST /api/v1/projects/{project_id}/slides/generate` (`{ "summary_split_mode": "SPLIT_2", "use_approved_only": true }`)
- `GET /api/v1/projects/{project_id}/slides`

#### 2) 슬라이드 수동 편집
- `PATCH /api/v1/projects/{project_id}/slides/{slide_id}` (`headcopy`, `bullets`, `table`, `as_is_to_be`, `review_status` 등 부분 수정)

#### 3) 기획자 코멘트 AI 윤문 (Diff 프리뷰) & 최종 결정
- `POST /api/v1/projects/{project_id}/slides/{slide_id}/apply-comment`
  - Request: `{ "raw_comment": "2030 입문자 관점에서의 첫 안티에이징 소구 필요성을 리드 문장에 강조해줘", "auto_apply": false }`
  - Response (`CommentDiffResponse`): `comment_id`, `refined_comment`, `before_draft` (`headcopy`, `bullets`, `as_is_to_be`), `after_draft`.
- `POST /api/v1/projects/{project_id}/slides/{slide_id}/comments/{comment_id}/decide`
  - Request: `{ "decision": "APPLY" }` 또는 `{ "decision": "REVERT" }`

#### 4) 현황 요약(Summary) 2장 ↔ 4장 분할 전환 & 섹션 일괄 승인
- `PATCH /api/v1/projects/{project_id}/summary-split` (`{ "summary_split_mode": "SPLIT_4" }`)
- `POST /api/v1/projects/{project_id}/sections/{section_code}/approve`

---

### Step 4. 사전 QC 검증 & 팩트북 PPT 출력 (`/projects/[id]/export`, `ppt-export`)
> **핵심 UX**: 출력 전 4대 QC 게이트 결과를 체크리스트로 노출하고, `BLOCKER`가 있으면 문제 슬라이드 ID/섹션 링크를 눌러 즉시 보완, `PASS`/`WARNING` 시 PPTX 생성 및 다운로드.

#### 1) 사전 QC 점검
- `POST /api/v1/projects/{project_id}/exports/qc`
- **Response (`QcReportResponse`)**:
  - `overall_status`: `PASS` | `WARNING` | `BLOCKER`
  - `can_export`: `boolean`
  - `missing_sections`: `SectionCode[]`
  - `checks`: `[REQUIRED_SECTIONS, NO_EMPTY_SLIDES, EVIDENCE_AND_DATALAB_BASIS, MEDIA_AND_OVERFLOW]` 4대 게이트 상세 결과

#### 2) PPTX 생성 & 바이너리 다운로드
- `POST /api/v1/projects/{project_id}/exports/pptx` (`{ "allow_warnings": true }`) → `ExportRecordResponse` (`id`, `slide_count`, `file_size_bytes`, `download_url`)
- `GET /api/v1/projects/{project_id}/exports` → 출력 이력 목록
- `GET /api/v1/projects/{project_id}/exports/{export_id}/download` → `.pptx` 파일 스트리밍 다운로드
