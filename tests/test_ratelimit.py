from __future__ import annotations

from weather_bot.ratelimit import SlidingWindowLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_eleventh_call_in_a_window_is_rejected() -> None:
    limiter = SlidingWindowLimiter(limit=10, window=60, clock=FakeClock())
    results = [limiter.allow("chat") for _ in range(11)]
    assert results == [True] * 10 + [False]


def test_budget_recovers_after_the_window() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=2, window=60, clock=clock)
    assert limiter.allow(1) and limiter.allow(1) and not limiter.allow(1)
    clock.now = 60
    assert limiter.allow(1)


def test_keys_are_independent() -> None:
    limiter = SlidingWindowLimiter(limit=1, window=60, clock=FakeClock())
    assert limiter.allow("a") and limiter.allow("b")
    assert not limiter.allow("a")


def test_idle_keys_are_evicted_when_tracking_is_full(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr("weather_bot.ratelimit.MAX_TRACKED_KEYS", 3)
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=1, window=10, clock=clock)
    for key in "abc":
        limiter.allow(key)
    clock.now = 20
    limiter.allow("d")
    assert set(limiter._hits) == {"d"}  # noqa: SLF001
