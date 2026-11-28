# `ptk-v2` MADP 프로덕션 배포 및 운영 가이드

`PTKOREA-DIVISION-4/PTK_V2_BE` 백엔드를 MADP 서버(`ptk-api`, Ubuntu 24.04, 사설 IP `10.0.0.91`)에 Docker Compose(`api` + `mysql:8.0`)로 배포하고, `main` 브랜치 push 시 GitHub Actions Self-hosted Runner로 자동 배포하는 운영 문서입니다.

---

## 1. 아키텍처 개요

- **컨테이너 구성 (`deploy/docker-compose.prod.yml`, 프로젝트명 `ptk-v2`)**
  - `api`: FastAPI + Uvicorn (`0.0.0.0:8000`, 헬스체크 `GET /health`), Pretendard 정적 폰트 내장, `/app/storage`에 `storage_data` 도커 볼륨 마운트
  - `db`: MySQL 8.0 (`utf8mb4`, `mysqldata` 도커 볼륨 마운트, RAM 3.8GB 환경에 맞춰 `--innodb-buffer-pool-size=256M --performance-schema=OFF`, **호스트 포트 미개방**)
- **네트워크 및 HTTPS**
  - MADP 게이트웨이가 `10.0.0.91:8000`으로 트래픽을 프록시하므로 컨테이너 내부에 별도 ngrok/Caddy/SSL 종료가 필요하지 않습니다.
  - 공개 주소: `https://division4.madp.cloud`
  - CORS 허용: `https://division4.madp.cloud`, `http://localhost:3000`, `http://127.0.0.1:3000` 및 Vercel 배포 도메인(`^https://[a-zA-Z0-9-]+\.vercel\.app$`)
- **CI/CD 흐름 (`.github/workflows/deploy.yml`)**
  1. `test`: `.github/workflows/ci.yml` (`pytest`) 실행
  2. `build`: Docker 이미지 빌드 후 `ghcr.io/ptkorea-division-4/ptk-v2:<sha>` / `:latest` 푸시
  3. `deploy`: `[self-hosted, madp-ptk-v2]` 러너가 `/opt/ptk-v2`에서 `deploy/deploy.sh` 실행 → 헬스체크 통과 시 `current_image` 갱신, 실패 시 직전 이미지로 자동 롤백

---

## 2. 초기 서버 준비 절차

1. **서버 서비스 폴더 생성**
   ```bash
   tsh ssh ubuntu@ptk-api 'sudo mkdir -p /opt/ptk-v2 && sudo chown ubuntu: /opt/ptk-v2'
   ```

2. **프로덕션 `.env` 생성 및 설치 (`600` 권한)**
   ```bash
   cd backend
   SSH="tsh ssh" deploy/make-env.sh ubuntu@ptk-api
   tsh ssh ubuntu@ptk-api 'ls -l /opt/ptk-v2/.env'
   ```
   - `deploy/.env.server`는 `.gitignore`로 추적 제외되며, 실행 시 값 대신 키 이름만 출력됩니다.

3. **Self-hosted GitHub Actions 러너 등록 (`~/actions-runner-ptk-v2`)**
   ```bash
   TOKEN=$(gh api -X POST repos/PTKOREA-DIVISION-4/PTK_V2_BE/actions/runners/registration-token --jq .token)
   VER=$(gh api repos/actions/runner/releases/latest --jq .tag_name | sed 's/^v//')
   tsh ssh ubuntu@ptk-api "mkdir -p ~/actions-runner-ptk-v2 && cd ~/actions-runner-ptk-v2 && curl -fsSL -o r.tgz https://github.com/actions/runner/releases/download/v$VER/actions-runner-linux-x64-$VER.tar.gz && tar xzf r.tgz && rm r.tgz && ./config.sh --url https://github.com/PTKOREA-DIVISION-4/PTK_V2_BE --token $TOKEN --labels madp-ptk-v2 --name ptk-v2-ptk-api --unattended --replace && sudo ./svc.sh install ubuntu && sudo ./svc.sh start"
   ```
   - 상태 확인: `gh api repos/PTKOREA-DIVISION-4/PTK_V2_BE/actions/runners --jq '.runners[] | {name,status}'` (`online` 확인)

4. **GitHub `production` 환경 생성**
   ```bash
   gh api -X PUT repos/PTKOREA-DIVISION-4/PTK_V2_BE/environments/production
   ```

---

## 3. 배포 및 공개 도메인 연결

1. **자동 배포 확인 (`main` 머지 후)**
   ```bash
   gh run watch -R PTKOREA-DIVISION-4/PTK_V2_BE
   # 필요 시 수동 재실행:
   gh workflow run deploy.yml -R PTKOREA-DIVISION-4/PTK_V2_BE --ref main
   ```
   - GHCR 이미지가 private일 경우 `GitHub → Packages → ptk-v2 → Package settings → Manage Actions access`에 `PTKOREA-DIVISION-4/PTK_V2_BE`를 추가하세요.

2. **서버 내부 확인**
   ```bash
   tsh ssh ubuntu@ptk-api 'curl -s localhost:8000/health && echo "" && docker compose -f /opt/ptk-v2/docker-compose.yml ps && free -h'
   ```

3. **MADP 공개 도메인 연결 및 확인**
   - MADP MCP `expose_web(instance_name="ptk-api", subdomain="division4", port=8000)` 호출 후 확인:
   ```bash
   curl -i https://division4.madp.cloud/health
   ```
   - 프론트엔드(Vercel) 환경변수 `NEXT_PUBLIC_API_BASE_URL`은 `https://division4.madp.cloud`로 설정합니다.

---

## 4. 운영 명령 모음

### 로그 확인
```bash
tsh ssh ubuntu@ptk-api 'docker compose -f /opt/ptk-v2/docker-compose.yml logs -f --tail 100 api'
tsh ssh ubuntu@ptk-api 'docker compose -f /opt/ptk-v2/docker-compose.yml logs -f --tail 100 db'
```

### 직전 이미지로 수동 롤백
```bash
tsh ssh ubuntu@ptk-api '
cd /opt/ptk-v2
API_IMAGE=$(cat current_image) docker compose up -d api
curl -fsS http://127.0.0.1:8000/health
'
```
*(특정 커밋 SHA 이미지로 되돌리려면 `API_IMAGE=ghcr.io/ptkorea-division-4/ptk-v2:<sha> docker compose up -d api`를 실행하세요.)*

### MySQL 백업 및 복구
```bash
# 백업 (압축 파일로 저장)
tsh ssh ubuntu@ptk-api '
cd /opt/ptk-v2 && set -a && . ./.env && set +a
docker compose exec -T db mysqldump -ufactbook -p"$MYSQL_PASSWORD" --single-transaction --routines --triggers factbook | gzip > ~/factbook-$(date +%Y%m%d-%H%M%S).sql.gz
'

# 복구
tsh ssh ubuntu@ptk-api '
cd /opt/ptk-v2 && set -a && . ./.env && set +a
gunzip -c ~/factbook-YYYYMMDD-HHMMSS.sql.gz | docker compose exec -T db mysql -ufactbook -p"$MYSQL_PASSWORD" factbook
'
```

### 환경변수(`.env`) 갱신 후 반영
```bash
cd backend
SSH="tsh ssh" deploy/make-env.sh ubuntu@ptk-api
tsh ssh ubuntu@ptk-api 'cd /opt/ptk-v2 && API_IMAGE=$(cat current_image) docker compose up -d api'
```
