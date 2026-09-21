import logging

import httpx

from mergency.domain.models.budget_severity import BudgetSeverity

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.giphy.com/v1/gifs/search"
_TIMEOUT_SECONDS = 2.0

_SEARCH_KEYWORDS = {
    BudgetSeverity.WARN: "alarm",
    BudgetSeverity.BREACH: "disaster",
}

_FALLBACK_GIF_URLS = {
    BudgetSeverity.WARN: "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
    BudgetSeverity.BREACH: "https://media.giphy.com/media/3o7TKSjRrfIPjeiVyM/giphy.gif",
}


class GiphyClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def gif_for_severity(self, severity: BudgetSeverity) -> str:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.get(
                    _SEARCH_URL,
                    params={
                        "api_key": self._api_key,
                        "q": _SEARCH_KEYWORDS[severity],
                        "limit": 1,
                    },
                )
                response.raise_for_status()
                results = response.json()["data"]
                return results[0]["images"]["original"]["url"]
        except (httpx.HTTPError, KeyError, IndexError) as error:
            logger.warning(
                "giphy lookup failed, using fallback gif",
                extra={"severity": severity.value, "error": str(error)},
            )
            return _FALLBACK_GIF_URLS[severity]
