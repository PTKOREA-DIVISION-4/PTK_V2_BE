from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers import (
    collections,
    exports,
    jobs,
    projects,
    research_plans,
    reviews,
)
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, init_db
from app.core.exceptions import AppException
from app.core.job_manager import JobManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.session_factory = AsyncSessionLocal
    app.state.job_manager = JobManager(AsyncSessionLocal)
    if settings.DB_AUTO_CREATE_TABLES:
        await init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description=(
            "PTKOREA Factbook Generator Backend API. "
            "단일 브랜드·제품 단위 리서치, 5종 API 비동기 수집, 일괄 검수·기획자 코멘트 윤문, "
            "사전 QC 검증 및 0~5장 표준 목차 PPTX 출력을 제공합니다."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppException)
    async def handle_app_exception(_: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_error_envelope())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                {
                    "error": {
                        "code": "REQUEST_VALIDATION_ERROR",
                        "message": "요청 데이터 형식이 올바르지 않습니다.",
                        "user_action_hint": "필수 입력 항목과 날짜/URL 형식을 확인해 주세요.",
                        "details": exc.errors(),
                        "retryable": False,
                    }
                }
            ),
        )

    @app.get("/health", tags=["System"])
    async def health_check() -> dict[str, object]:
        return {
            "status": "ok",
            "app_name": settings.APP_NAME,
            "api_readiness": settings.api_key_readiness(),
        }

    prefix = settings.API_V1_PREFIX
    app.include_router(projects.router, prefix=prefix)
    app.include_router(research_plans.router, prefix=prefix)
    app.include_router(collections.router, prefix=prefix)
    app.include_router(reviews.router, prefix=prefix)
    app.include_router(exports.router, prefix=prefix)
    app.include_router(jobs.router, prefix=prefix)

    # Serve locally archived thumbnails & captures for frontend review UI
    app.mount("/media", StaticFiles(directory=str(settings.media_dir)), name="media")

    return app


app = create_app()
