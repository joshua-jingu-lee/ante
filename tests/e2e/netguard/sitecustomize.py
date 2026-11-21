"""e2e 하위 프로세스에서 유닉스 소켓이 아닌 접속을 모두 막고 기록하는 가드."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
from typing import Any

LOG_ENV = "ANTE_E2E_NETGUARD_LOG"
MARKER_ENV = "ANTE_E2E_NETGUARD_MARKER"

_log_path = os.environ.get(LOG_ENV)
_marker_path = os.environ.get(MARKER_ENV)
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex


def _caller_modules() -> list[str]:
    names: list[str] = []
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_globals.get("__name__", "?")
        if name != __name__ and (not names or names[-1] != name):
            names.append(name)
        frame = frame.f_back
    return names


def _append(path: str | None, line: str) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _blocked(kind: str, target: Any) -> str:
    entry = {
        "pid": os.getpid(),
        "kind": kind,
        "target": repr(target),
        "thread": threading.current_thread().name,
        "modules": _caller_modules(),
    }
    _append(_log_path, json.dumps(entry, ensure_ascii=False))
    return f"e2e netguard blocked {kind} to {target!r}"


def _guarded_connect(self: socket.socket, address: Any) -> None:
    if self.family == socket.AF_UNIX:
        return _original_connect(self, address)
    raise OSError(_blocked("connect", address))


def _guarded_connect_ex(self: socket.socket, address: Any) -> int:
    if self.family == socket.AF_UNIX:
        return _original_connect_ex(self, address)
    raise OSError(_blocked("connect_ex", address))


def _guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
    raise socket.gaierror(_blocked("getaddrinfo", host))


def _guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
    raise OSError(_blocked("create_connection", address))


socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign]
socket.getaddrinfo = _guarded_getaddrinfo
socket.create_connection = _guarded_create_connection
_append(_marker_path, str(os.getpid()))
