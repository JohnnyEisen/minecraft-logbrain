import asyncio

import pytest

from brain_system.retry import CircuitBreaker, CircuitState, RetryPolicy, async_retry


@pytest.mark.asyncio
async def test_async_retry_succeeds_after_failures():
    attempts = {"n": 0}

    async def fn():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TimeoutError("x")
        return 42

    r = await async_retry(fn, policy=RetryPolicy(max_attempts=5, initial_delay_seconds=0.0))
    assert r == 42


@pytest.mark.asyncio
async def test_async_retry_cancelled_error_does_not_open_circuit_breaker():
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0, success_threshold=1)

    async def fn():
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await async_retry(fn, policy=RetryPolicy(max_attempts=3, circuit_breaker=breaker))

    assert breaker.state == CircuitState.CLOSED
    assert breaker.get_stats()["failures"] == 0
