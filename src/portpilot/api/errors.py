"""Contract error shape (docs/api/CONTRACT.md): `{"error": {"code", "message"}}`."""

from __future__ import annotations

from fastapi import HTTPException


class ApiError(HTTPException):
    """An HTTPException whose body is already the contract's error shape."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(
            status_code=status_code, detail={"error": {"code": code, "message": message}}
        )


def bad_request(message: str) -> ApiError:
    return ApiError(400, "bad_request", message)


def unauthorized(message: str = "missing or invalid bearer token") -> ApiError:
    return ApiError(401, "unauthorized", message)


def not_found(message: str) -> ApiError:
    return ApiError(404, "not_found", message)


def conflict(message: str) -> ApiError:
    return ApiError(409, "conflict", message)


def invalid_repo_url(message: str = "repo_url is invalid") -> ApiError:
    return ApiError(422, "invalid_repo_url", message)


def invalid_goal(message: str = "goal must be 3-2000 characters") -> ApiError:
    return ApiError(422, "invalid_goal", message)


def rate_limited(message: str = "too many runs created; try again later") -> ApiError:
    return ApiError(429, "rate_limited", message)
