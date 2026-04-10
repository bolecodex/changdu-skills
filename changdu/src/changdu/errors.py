"""Typed exceptions and stable exit codes."""

from __future__ import annotations

from dataclasses import dataclass


class ChangduError(Exception):
    """Base class for application-level errors."""

    code = "E_INTERNAL"
    exit_code = 1

    def __init__(self, message: str, request_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.request_id = request_id


class ConfigError(ChangduError):
    code = "E_CONFIG"
    exit_code = 10


class AuthError(ChangduError):
    code = "E_AUTH"
    exit_code = 11


class RequestError(ChangduError):
    code = "E_REQUEST"
    exit_code = 12


class ServerError(ChangduError):
    code = "E_SERVER"
    exit_code = 13


class TimeoutError(ChangduError):
    code = "E_TIMEOUT"
    exit_code = 14


class NetworkError(ChangduError):
    code = "E_NETWORK"
    exit_code = 15


class TrajectoryError(ChangduError):
    code = "E_TRAJECTORY"
    exit_code = 16


@dataclass(frozen=True)
class ErrorPayload:
    code: str
    message: str
    request_id: str | None = None
