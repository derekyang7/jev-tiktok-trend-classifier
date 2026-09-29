import httpx
import pytest

from jevtrends.config import RetriesCfg
from jevtrends.http import FatalAPIError, TransientAPIError, send_with_retry

RETRIES = RetriesCfg(max_attempts=3, base_delay_s=1, max_delay_s=30)


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class Sleeps:
    def __init__(self):
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


async def test_success_on_first_try():
    async with client_for(lambda req: httpx.Response(200, json={"ok": True})) as client:
        resp = await send_with_retry(client, "jev", "POST", "https://x/y", retries=RETRIES, json={})
    assert resp.json() == {"ok": True}


async def test_retries_429_and_honors_retry_after():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "2"}, text="slow down")
        return httpx.Response(200, json={"ok": True})

    sleeps = Sleeps()
    async with client_for(handler) as client:
        resp = await send_with_retry(client, "jev", "GET", "https://x/y", retries=RETRIES, sleep=sleeps)
    assert resp.status_code == 200
    assert len(calls) == 2
    assert sleeps.delays == [2.0]


async def test_fatal_status_is_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, text="bad key")

    async with client_for(handler) as client:
        with pytest.raises(FatalAPIError) as err:
            await send_with_retry(client, "openrouter", "GET", "https://x/y", retries=RETRIES, sleep=Sleeps())
    assert err.value.status == 401 and err.value.provider == "openrouter"
    assert len(calls) == 1


async def test_transient_error_after_all_attempts():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, text="overloaded")

    sleeps = Sleeps()
    async with client_for(handler) as client:
        with pytest.raises(TransientAPIError) as err:
            await send_with_retry(client, "jev", "GET", "https://x/y", retries=RETRIES, sleep=sleeps)
    assert err.value.status == 503
    assert len(calls) == 3
    assert len(sleeps.delays) == 2
    assert all(0.5 <= d <= 30 for d in sleeps.delays)


async def test_connection_errors_are_retried():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    async with client_for(handler) as client:
        with pytest.raises(TransientAPIError):
            await send_with_retry(client, "scrapecreators", "GET", "https://x/y", retries=RETRIES, sleep=Sleeps())


async def test_any_5xx_is_retried_including_cloudflare_520():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(520, json={"error": {"message": "HTTP 520: error code: 520", "code": 520}})
        return httpx.Response(200, json={"ok": True})

    async with client_for(handler) as client:
        resp = await send_with_retry(client, "jev", "POST", "https://x/y", retries=RETRIES, sleep=Sleeps())
    assert resp.status_code == 200 and len(calls) == 2
