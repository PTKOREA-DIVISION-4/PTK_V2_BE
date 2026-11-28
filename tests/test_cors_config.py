from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


def test_cors_origin_regex_allows_vercel_and_blocks_unknown(monkeypatch) -> None:
    monkeypatch.setenv(
        "CORS_ORIGINS",
        '["https://division4.madp.cloud","http://localhost:3000"]',
    )
    monkeypatch.setenv("CORS_ORIGIN_REGEX", r"^https://[a-zA-Z0-9-]+\.vercel\.app$")
    get_settings.cache_clear()

    try:
        app = create_app()
        client = TestClient(app)

        vercel_res = client.options(
            "/health",
            headers={
                "Origin": "https://ptk-v2-fe.vercel.app",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert vercel_res.status_code == 200
        assert vercel_res.headers.get("access-control-allow-origin") == "https://ptk-v2-fe.vercel.app"

        madp_res = client.options(
            "/health",
            headers={
                "Origin": "https://division4.madp.cloud",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert madp_res.status_code == 200
        assert madp_res.headers.get("access-control-allow-origin") == "https://division4.madp.cloud"

        blocked_res = client.options(
            "/health",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in blocked_res.headers
    finally:
        get_settings.cache_clear()
