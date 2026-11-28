"""Process-local sliding-window guard for AI endpoint bursts.

This is defense in depth only: a shared Redis/database limiter is required for
strict cross-worker or cross-instance enforcement.
"""
from collections import OrderedDict, deque
from threading import Lock
import time

from fastapi import HTTPException


_DEFAULT_LIMIT = 10
_DEFAULT_WINDOW_SECONDS = 60
_MAX_TRACKED_USERS = 10000
_requests: OrderedDict[str, deque[float]] = OrderedDict()
_lock = Lock()


def enforce_ai_rate_limit(user_id: str) -> None:
    """Allow at most ten AI calls per user per minute in this API process."""
    now = time.monotonic()
    cutoff = now - _DEFAULT_WINDOW_SECONDS
    with _lock:
        history = _requests.get(user_id)
        if history is None:
            history = deque()
            _requests[user_id] = history
        else:
            _requests.move_to_end(user_id)

        while history and history[0] <= cutoff:
            history.popleft()

        if len(history) >= _DEFAULT_LIMIT:
            retry_after = max(1, int(_DEFAULT_WINDOW_SECONDS - (now - history[0])))
            raise HTTPException(
                status_code=429,
                detail="Слишком много AI-запросов. Подождите немного и повторите.",
                headers={"Retry-After": str(retry_after)},
            )

        history.append(now)
        while len(_requests) > _MAX_TRACKED_USERS:
            _requests.popitem(last=False)


def _reset_rate_limit_state_for_tests() -> None:
    with _lock:
        _requests.clear()
