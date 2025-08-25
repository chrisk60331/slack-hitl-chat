"""GIF service for searching and retrieving GIFs from various APIs."""

import os
import random

import requests

from .models import (
    GetRandomGifRequest,
    GetTrendingGifsRequest,
    GifResult,
    SearchGifsRequest,
    SearchGifsResponse,
    SlackGifMessage,
)


class GifService:
    """Service for interacting with GIF APIs and formatting responses for Slack."""

    def __init__(self):
        """Initialize the GIF service with API keys."""
        self.giphy_api_key = os.environ.get("GIPHY_API_KEY")
        self.tenor_api_key = os.environ.get("TENOR_API_KEY")
        self.default_source = (
            "giphy" if self.giphy_api_key else "tenor" if self.tenor_api_key else "mock"
        )

    def search_gifs(self, request: SearchGifsRequest) -> SearchGifsResponse:
        """
        Search for GIFs using available APIs.

        Args:
            request: Search parameters including query and filters

        Returns:
            SearchGifsResponse with found GIFs and metadata
        """
        if self.giphy_api_key:
            return self._search_giphy(request)
        elif self.tenor_api_key:
            return self._search_tenor(request)
        else:
            return self._search_mock(request)

    def get_random_gif(self, request: GetRandomGifRequest) -> GifResult:
        """
        Get a random GIF based on optional tag.

        Args:
            request: Random GIF request with optional tag filter

        Returns:
            Random GIF result
        """
        if self.giphy_api_key:
            return self._get_random_giphy(request)
        elif self.tenor_api_key:
            return self._get_random_tenor(request)
        else:
            return self._get_random_mock(request)

    def get_trending_gifs(self, request: GetTrendingGifsRequest) -> SearchGifsResponse:
        """
        Get currently trending GIFs.

        Args:
            request: Trending GIFs request with time period filter

        Returns:
            Trending GIFs response
        """
        if self.giphy_api_key:
            return self._get_trending_giphy(request)
        elif self.tenor_api_key:
            return self._get_trending_tenor(request)
        else:
            return self._get_trending_mock(request)

    def format_for_slack(self, gif: GifResult, message: str = "") -> SlackGifMessage:
        """
        Format a GIF result for Slack display.

        Args:
            gif: GIF result to format
            message: Optional text message to accompany the GIF

        Returns:
            Slack-formatted GIF message
        """
        text = message or f"Here's a GIF: {gif.title}"

        # Create Slack blocks for rich formatting
        # Note: Slack image blocks require the image to be publicly accessible
        # and the domain to be allowed in Slack workspace settings
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]

        # Add image block if the GIF URL is accessible
        # For now, we'll include the image block but Slack may need domain allowlisting
        try:
            blocks.append(
                {
                    "type": "image",
                    "image_url": gif.url,
                    "alt_text": gif.title,
                    "title": {"type": "plain_text", "text": gif.title},
                }
            )
        except Exception:
            # Fallback: just include the URL in the text
            pass

        return SlackGifMessage(
            text=text, gif_url=gif.url, gif_title=gif.title, blocks=blocks
        )

    def _search_giphy(self, request: SearchGifsRequest) -> SearchGifsResponse:
        """Search GIFs using Giphy API."""
        url = "https://api.giphy.com/v1/gifs/search"
        params = {
            "api_key": self.giphy_api_key,
            "q": request.query,
            "limit": request.limit,
            "rating": request.rating,
            "lang": request.language,
            "offset": request.offset,
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            gifs = []
            for gif_data in data.get("data", []):
                gif = GifResult(
                    id=gif_data["id"],
                    title=gif_data["title"],
                    url=gif_data["images"]["original"]["url"],
                    preview_url=gif_data["images"]["preview_gif"]["url"],
                    width=int(gif_data["images"]["original"]["width"]),
                    height=int(gif_data["images"]["original"]["height"]),
                    size=int(gif_data["images"]["original"]["size"])
                    if gif_data["images"]["original"]["size"]
                    else None,
                    source="giphy",
                )
                gifs.append(gif)

            return SearchGifsResponse(
                gifs=gifs,
                total_count=data.get("pagination", {}).get("total_count", len(gifs)),
                query=request.query,
                pagination=data.get("pagination", {}),
            )
        except Exception:
            # Fallback to mock data on error
            return self._search_mock(request)

    def _search_tenor(self, request: SearchGifsRequest) -> SearchGifsResponse:
        """Search GIFs using Tenor API."""
        url = "https://tenor.googleapis.com/v2/search"
        params = {
            "key": self.tenor_api_key,
            "q": request.query,
            "limit": request.limit,
            "client_key": "agentcore_marketplace",
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            gifs = []
            for gif_data in data.get("results", []):
                gif = GifResult(
                    id=gif_data["id"],
                    title=gif_data.get("title", "Tenor GIF"),
                    url=gif_data["media_formats"]["gif"]["url"],
                    preview_url=gif_data["media_formats"]["tinygif"]["url"],
                    width=int(gif_data["media_formats"]["gif"]["dims"][0]),
                    height=int(gif_data["media_formats"]["gif"]["dims"][1]),
                    size=None,  # Tenor doesn't provide file size
                    source="tenor",
                )
                gifs.append(gif)

            return SearchGifsResponse(
                gifs=gifs,
                total_count=data.get("next", "").split("=")[-1]
                if data.get("next")
                else len(gifs),
                query=request.query,
                pagination={"next": data.get("next")},
            )
        except Exception:
            # Fallback to mock data on error
            return self._search_mock(request)

    def _search_mock(self, request: SearchGifsRequest) -> SearchGifsResponse:
        """Provide mock GIF data for testing/fallback."""
        mock_gifs = [
            GifResult(
                id="mock_1",
                title=f"Mock GIF for: {request.query}",
                url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif",
                preview_url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif",
                width=480,
                height=270,
                size=1024000,
                source="mock",
            ),
            GifResult(
                id="mock_2",
                title=f"Another mock GIF for: {request.query}",
                url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif",
                preview_url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif",
                width=480,
                height=270,
                size=1024000,
                source="mock",
            ),
        ]

        return SearchGifsResponse(
            gifs=mock_gifs[: request.limit],
            total_count=len(mock_gifs),
            query=request.query,
            pagination={"offset": request.offset, "limit": request.limit},
        )

    def _get_random_giphy(self, request: GetRandomGifRequest) -> GifResult:
        """Get random GIF from Giphy."""
        url = "https://api.giphy.com/v1/gifs/random"
        params = {
            "api_key": self.giphy_api_key,
            "tag": request.tag or "",
            "rating": request.rating,
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            gif_data = data["data"]
            return GifResult(
                id=gif_data["id"],
                title=gif_data["title"],
                url=gif_data["images"]["original"]["url"],
                preview_url=gif_data["images"]["preview_gif"]["url"],
                width=int(gif_data["images"]["original"]["width"]),
                height=int(gif_data["images"]["original"]["height"]),
                size=int(gif_data["images"]["original"]["size"])
                if gif_data["images"]["original"]["size"]
                else None,
                source="giphy",
            )
        except Exception:
            return self._get_random_mock(request)

    def _get_random_tenor(self, request: GetRandomGifRequest) -> GifResult:
        """Get random GIF from Tenor."""
        # Tenor doesn't have a direct random endpoint, so we'll search and pick random
        search_request = SearchGifsRequest(
            query=request.tag or "random", limit=20, rating=request.rating
        )
        search_response = self._search_tenor(search_request)

        if search_response.gifs:
            return random.choice(search_response.gifs)
        else:
            return self._get_random_mock(request)

    def _get_random_mock(self, request: GetRandomGifRequest) -> GifResult:
        """Get random mock GIF."""
        mock_gifs = [
            GifResult(
                id="random_mock_1",
                title=f"Random mock GIF{f' for {request.tag}' if request.tag else ''}",
                url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif",
                preview_url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif",
                width=480,
                height=270,
                size=1024000,
                source="mock",
            ),
            GifResult(
                id="random_mock_2",
                title=f"Another random mock GIF{f' for {request.tag}' if request.tag else ''}",
                url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif",
                preview_url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif",
                width=480,
                height=270,
                size=1024000,
                source="mock",
            ),
        ]

        return random.choice(mock_gifs)

    def _get_trending_giphy(
        self, request: GetTrendingGifsRequest
    ) -> SearchGifsResponse:
        """Get trending GIFs from Giphy."""
        url = "https://api.giphy.com/v1/gifs/trending"
        params = {
            "api_key": self.giphy_api_key,
            "limit": request.limit,
            "rating": request.rating,
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            gifs = []
            for gif_data in data.get("data", []):
                gif = GifResult(
                    id=gif_data["id"],
                    title=gif_data["title"],
                    url=gif_data["images"]["original"]["url"],
                    preview_url=gif_data["images"]["preview_gif"]["url"],
                    width=int(gif_data["images"]["original"]["width"]),
                    height=int(gif_data["images"]["original"]["height"]),
                    size=int(gif_data["images"]["original"]["size"])
                    if gif_data["images"]["original"]["size"]
                    else None,
                    source="giphy",
                )
                gifs.append(gif)

            return SearchGifsResponse(
                gifs=gifs,
                total_count=len(gifs),
                query="trending",
                pagination={"limit": request.limit},
            )
        except Exception:
            return self._get_trending_mock(request)

    def _get_trending_tenor(
        self, request: GetTrendingGifsRequest
    ) -> SearchGifsResponse:
        """Get trending GIFs from Tenor."""
        url = "https://tenor.googleapis.com/v2/featured"
        params = {
            "key": self.tenor_api_key,
            "limit": request.limit,
            "client_key": "agentcore_marketplace",
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            gifs = []
            for gif_data in data.get("results", []):
                gif = GifResult(
                    id=gif_data["id"],
                    title=gif_data.get("title", "Trending Tenor GIF"),
                    url=gif_data["media_formats"]["gif"]["url"],
                    preview_url=gif_data["media_formats"]["tinygif"]["url"],
                    width=int(gif_data["media_formats"]["gif"]["dims"][0]),
                    height=int(gif_data["media_formats"]["gif"]["dims"][1]),
                    size=None,
                    source="tenor",
                )
                gifs.append(gif)

            return SearchGifsResponse(
                gifs=gifs,
                total_count=len(gifs),
                query="trending",
                pagination={"limit": request.limit},
            )
        except Exception:
            return self._get_trending_mock(request)

    def _get_trending_mock(self, request: GetTrendingGifsRequest) -> SearchGifsResponse:
        """Get trending mock GIFs."""
        mock_gifs = [
            GifResult(
                id="trending_mock_1",
                title="Trending mock GIF 1",
                url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif",
                preview_url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif",
                width=480,
                height=270,
                size=1024000,
                source="mock",
            ),
            GifResult(
                id="trending_mock_2",
                title="Trending mock GIF 2",
                url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif",
                preview_url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif",
                width=480,
                height=270,
                size=1024000,
                source="mock",
            ),
        ]

        return SearchGifsResponse(
            gifs=mock_gifs[: request.limit],
            total_count=len(mock_gifs),
            query="trending",
            pagination={"limit": request.limit},
        )
