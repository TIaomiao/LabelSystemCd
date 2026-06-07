from __future__ import annotations

from collections.abc import Callable


class JobPaused(RuntimeError):
    """Raised when a running background job is asked to stop."""


ProgressCallback = Callable[[int, int, str | None], None]
ShouldPauseCallback = Callable[[], bool]

