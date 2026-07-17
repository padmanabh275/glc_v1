"""Data-plane rate limits and daily budgets (C5, invariant 8)."""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class _Bucket:
    hits: deque[float] = field(default_factory=deque)
    day_count: int = 0
    day_key: str = ""


class DataPlaneLimiter:
    def __init__(
        self,
        rpm: int | None = None,
        daily_budget: int | None = None,
    ) -> None:
        self.rpm = int(os.getenv("GLC_DATA_PLANE_RPM", str(rpm if rpm is not None else 60)))
        self.daily_budget = int(
            os.getenv("GLC_DATA_PLANE_DAILY_BUDGET", str(daily_budget if daily_budget is not None else 5000))
        )
        self._state: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, str]:
        now = time.time()
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        with self._lock:
            b = self._state.setdefault(key, _Bucket())
            if b.day_key != day:
                b.day_key = day
                b.day_count = 0
            while b.hits and b.hits[0] < now - 60:
                b.hits.popleft()
            if len(b.hits) >= self.rpm:
                return False, f"data-plane rate limit {self.rpm}/min exceeded"
            if b.day_count >= self.daily_budget:
                return False, f"data-plane daily budget {self.daily_budget} exceeded"
            b.hits.append(now)
            b.day_count += 1
            return True, ""


_limiter: DataPlaneLimiter | None = None


def get_data_plane_limiter() -> DataPlaneLimiter:
    global _limiter
    if _limiter is None:
        _limiter = DataPlaneLimiter()
    return _limiter
