"""Event loop shared by the CLI and the server.

psycopg's async driver waits on selectors. Windows Python 3.14 defaults to
ProactorEventLoop, which has none, so the pool dies at startup with
"Psycopg cannot use the 'ProactorEventLoop'". uvicorn's built-in "asyncio"
loop is that same Proactor loop, so `uvicorn app.main:app` hits it too.

SelectorEventLoop is what psycopg needs, and it is the default everywhere
except Windows. Pass this factory to asyncio.run and to uvicorn:

    uvicorn app.main:app --loop app.runtime:selector_loop_factory
"""

from __future__ import annotations

import asyncio
import selectors
import sys
from collections.abc import Coroutine
from typing import Any


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop(selectors.SelectSelector())


def run(coro: Coroutine[Any, Any, Any]) -> Any:
    if sys.platform == "win32":
        return asyncio.run(coro, loop_factory=selector_loop_factory)
    return asyncio.run(coro)
