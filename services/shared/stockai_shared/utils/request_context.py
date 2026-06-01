from __future__ import annotations

import contextvars

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


def set_request_id(request_id: str) -> contextvars.Token:
    return _request_id_var.set(str(request_id or "-"))


def get_request_id() -> str:
    return _request_id_var.get()


def reset_request_id(token: contextvars.Token) -> None:
    _request_id_var.reset(token)
