import httpx

from mergency.adapters.giphy.giphy_client import _FALLBACK_GIF_URLS, GiphyClient
from mergency.domain.models.budget_severity import BudgetSeverity


class _StubResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _StubAsyncClient:
    def __init__(self, response: _StubResponse | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def get(self, url, params):
        if self._error is not None:
            raise self._error
        return self._response


def _payload_with_url(url: str) -> dict:
    return {"data": [{"images": {"original": {"url": url}}}]}


async def test_returns_the_first_search_result_url(monkeypatch):
    stub_client = _StubAsyncClient(
        response=_StubResponse(_payload_with_url("https://giphy.example/alarm.gif"))
    )
    monkeypatch.setattr(
        "mergency.adapters.giphy.giphy_client.httpx.AsyncClient", lambda **kwargs: stub_client
    )

    gif_url = await GiphyClient("test-api-key").gif_for_severity(BudgetSeverity.WARN)

    assert gif_url == "https://giphy.example/alarm.gif"


async def test_falls_back_to_the_configured_gif_when_giphy_times_out(monkeypatch):
    stub_client = _StubAsyncClient(error=httpx.TimeoutException("timed out"))
    monkeypatch.setattr(
        "mergency.adapters.giphy.giphy_client.httpx.AsyncClient", lambda **kwargs: stub_client
    )

    gif_url = await GiphyClient("test-api-key").gif_for_severity(BudgetSeverity.BREACH)

    assert gif_url == _FALLBACK_GIF_URLS[BudgetSeverity.BREACH]


async def test_falls_back_when_giphy_returns_no_results(monkeypatch):
    stub_client = _StubAsyncClient(response=_StubResponse({"data": []}))
    monkeypatch.setattr(
        "mergency.adapters.giphy.giphy_client.httpx.AsyncClient", lambda **kwargs: stub_client
    )

    gif_url = await GiphyClient("test-api-key").gif_for_severity(BudgetSeverity.WARN)

    assert gif_url == _FALLBACK_GIF_URLS[BudgetSeverity.WARN]


async def test_falls_back_on_an_unexpected_response_shape(monkeypatch):
    stub_client = _StubAsyncClient(response=_StubResponse({"data": [{"images": {}}]}))
    monkeypatch.setattr(
        "mergency.adapters.giphy.giphy_client.httpx.AsyncClient", lambda **kwargs: stub_client
    )

    gif_url = await GiphyClient("test-api-key").gif_for_severity(BudgetSeverity.BREACH)

    assert gif_url == _FALLBACK_GIF_URLS[BudgetSeverity.BREACH]
