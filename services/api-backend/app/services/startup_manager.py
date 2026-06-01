from __future__ import annotations

import inspect
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from fastapi import FastAPI


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class StartupStepStatus:
    number: int
    component: str
    label: str
    status: str
    detail: str = ""
    updated_at: str = field(default_factory=_utc_now_iso)


class StartupManager:
    """Centralized startup state manager for deterministic boot orchestration."""

    def __init__(self, app: FastAPI, logger: logging.Logger) -> None:
        self._app = app
        self._logger = logger
        self._phase = "BOOTING"
        self._steps: dict[str, StartupStepStatus] = {}
        self._publish()

    def _publish(self) -> None:
        self._app.state.startup_status = {
            "phase": self._phase,
            "updated_at": _utc_now_iso(),
            "steps": {
                name: asdict(step)
                for name, step in sorted(
                    self._steps.items(),
                    key=lambda item: item[1].number,
                )
            },
        }

    def _boot_log(self, message: str, *args: Any) -> None:
        # Keep detailed step logs available in DEBUG while lifespan prints
        # the operator-facing boot screen at INFO level.
        self._logger.debug(message, *args)

    def _set_step(
        self,
        *,
        number: int,
        component: str,
        label: str,
        status: str,
        detail: str = "",
    ) -> None:
        self._steps[component] = StartupStepStatus(
            number=number,
            component=component,
            label=label,
            status=status,
            detail=detail,
            updated_at=_utc_now_iso(),
        )
        self._publish()

    async def run_step(
        self,
        *,
        number: int,
        component: str,
        label: str,
        runner: Callable[[], Any | Awaitable[Any]],
        success_message: str | Callable[[Any], str] | None = None,
        critical: bool = True,
        abort_message: str = "Startup aborted. Please check configuration and dependencies.",
    ) -> Any:
        self._boot_log("[STARTUP] %s...", label)
        self._set_step(
            number=number,
            component=component,
            label=label,
            status="IN_PROGRESS",
        )

        try:
            result_or_awaitable = runner()
            result = (
                await result_or_awaitable
                if inspect.isawaitable(result_or_awaitable)
                else result_or_awaitable
            )
        except Exception as exc:
            self._phase = "FAILED"
            self._set_step(
                number=number,
                component=component,
                label=label,
                status="FAILED",
                detail=f"{type(exc).__name__}: {exc}",
            )
            self._logger.error("[STARTUP] %s... FAILED (%s)", label, exc)
            if critical:
                self._logger.error("[STARTUP] %s", abort_message)
                raise
            return None

        message = success_message
        if callable(success_message):
            message = success_message(result)

        self._set_step(
            number=number,
            component=component,
            label=label,
            status="READY",
            detail=str(message or "ready"),
        )

        if message:
            self._boot_log("[STARTUP] %s", message)
        else:
            self._boot_log("[STARTUP] %s complete.", label)
        return result

    def skip_step(
        self,
        *,
        number: int,
        component: str,
        label: str,
        reason: str,
    ) -> None:
        self._set_step(
            number=number,
            component=component,
            label=label,
            status="SKIPPED",
            detail=reason,
        )
        self._boot_log("[STARTUP] %s skipped (%s)", label, reason)

    def mark_ready(self, *, number: int, message: str) -> None:
        self._phase = "READY"
        self._publish()
        self._boot_log("[STARTUP] %s", message)

    def mark_stopping(self) -> None:
        self._phase = "STOPPING"
        self._publish()
