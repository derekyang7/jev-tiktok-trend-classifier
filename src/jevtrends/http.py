"""Shared HTTP retry policy (spec §12.2)."""

import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx

from jevtrends.config import RetriesCfg

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504, 529}


class APIError(Exception):
    def __init__(self, provider: str, status: int | None, message: str):
        super().__init__(f"{provider} request failed ({status}): {message}")
        self.provider = provider
        self.status = status


class FatalAPIError(APIError):
    """Non-retryable failure such as a rejected key or invalid request. Stops the scan."""


class TransientAPIError(APIError):
    """A retryable failure that persisted through every attempt. Fails only the current item."""


def backoff_delay(attempt: int, retries: RetriesCfg, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(float(retry_after), retries.max_delay_s)
        except ValueError:
            pass
    delay = min(retries.base_delay_s * 2 ** (attempt - 1), retries.max_delay_s)
    return delay * (0.5 + random.random() / 2)


async def send_with_retry(
    client: httpx.AsyncClient,
    provider: str,
    method: str,
    url: str,
    *,
    retries: RetriesCfg,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    **kwargs,
) -> httpx.Response:
    last_status: int | None = None
    last_error = ""
    for attempt in range(1, retries.max_attempts + 1):
        retry_after = None
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            last_status, last_error = None, type(exc).__name__
        else:
            if response.is_success:
                return response
            if response.status_code not in RETRYABLE_STATUS:
                raise FatalAPIError(provider, response.status_code, response.text[:300])
            last_status, last_error = response.status_code, response.text[:300]
            retry_after = response.headers.get("retry-after")
        if attempt < retries.max_attempts:
            await sleep(backoff_delay(attempt, retries, retry_after))
    raise TransientAPIError(provider, last_status, last_error)
