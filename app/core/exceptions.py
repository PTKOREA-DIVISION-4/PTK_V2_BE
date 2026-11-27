from __future__ import annotations

from typing import Any


class AppException(Exception):
    """Base domain exception converted into a consistent UI-friendly ErrorEnvelope."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 400,
        user_action_hint: str | None = None,
        details: list[dict[str, Any]] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.user_action_hint = user_action_hint
        self.details = details or []
        self.retryable = retryable

    def to_error_envelope(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "user_action_hint": self.user_action_hint,
                "details": self.details,
                "retryable": self.retryable,
            }
        }


class NotFoundError(AppException):
    def __init__(
        self,
        message: str = "요청한 리소스를 찾을 수 없습니다.",
        *,
        code: str = "RESOURCE_NOT_FOUND",
        user_action_hint: str | None = "목록으로 돌아가 대상을 다시 선택해 주세요.",
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=404,
            user_action_hint=user_action_hint,
            retryable=False,
        )


class ValidationDomainError(AppException):
    def __init__(
        self,
        message: str,
        *,
        code: str = "DOMAIN_VALIDATION_ERROR",
        user_action_hint: str | None = "입력값 형식을 확인한 뒤 다시 시도해 주세요.",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=422,
            user_action_hint=user_action_hint,
            details=details,
            retryable=False,
        )


class ConflictError(AppException):
    def __init__(
        self,
        message: str,
        *,
        code: str = "CONFLICT_STATE",
        user_action_hint: str | None = "진행 중인 작업이 완료된 후 다시 시도해 주세요.",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=409,
            user_action_hint=user_action_hint,
            details=details,
            retryable=False,
        )


class ExternalApiError(AppException):
    def __init__(
        self,
        *,
        provider: str,
        message: str,
        code: str = "EXTERNAL_API_ERROR",
        status_code: int = 502,
        user_action_hint: str | None = "잠시 후 실패한 소스만 선택하여 재시도해 주세요.",
        details: list[dict[str, Any]] | None = None,
        retryable: bool = True,
    ) -> None:
        merged_details = [{"provider": provider}, *(details or [])]
        super().__init__(
            code=code,
            message=message,
            status_code=status_code,
            user_action_hint=user_action_hint,
            details=merged_details,
            retryable=retryable,
        )
        self.provider = provider


class QcBlockedError(AppException):
    def __init__(
        self,
        message: str = "사전 품질 검증(QC)을 통과하지 못해 PPTX 출력을 차단했습니다.",
        *,
        code: str = "QC_BLOCKED",
        user_action_hint: str | None = "차단 사유를 확인하고 누락된 장표나 근거를 보완해 주세요.",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=400,
            user_action_hint=user_action_hint,
            details=details,
            retryable=False,
        )
