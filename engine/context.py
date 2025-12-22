
# context.py
"""Singleton-style holder so the SystemContext is built once per process.
Use init_context_*() from entrypoint (main.py) and pass get_context() to tests.
"""
from __future__ import annotations
from threading import RLock
from typing import Optional
from engine.models import SystemContext

_CTX: Optional[SystemContext] = None
_LOCK = RLock()


def init_context(ctx: SystemContext) -> SystemContext:
    global _CTX
    with _LOCK:
        if _CTX is None:
            _CTX = ctx
        return _CTX


def get_context() -> SystemContext:
    if _CTX is None:
        raise RuntimeError("Context not initialized. Call init_context(...) in main.py first.")
    return _CTX



