"""GIF service for searching and retrieving GIFs from various APIs."""

import os
import random

import dotenv
import requests

from .models import (
    GetRandomGifRequest,
    GetTrendingGifsRequest,
    GifResult,
    GifSource,
    SearchGifsRequest,
    SearchGifsResponse,
    SlackGifMessage,
)

dotenv.load_dotenv()

class GifService:
    """Service for interacting with GIF APIs and formatting responses for Slack."""

    def __init__(self):
        """Initialize the GIF service with API keys."""
        self.giphy_api_key = os.environ.get("GIPHY_API_KEY")
        self.tenor_api_key = os.environ.get("TENOR_API_KEY")
        self.default_source = (
            "giphy"
            if self.giphy_api_key
            else "tenor"
            if self.tenor_api_key
            else "unconfigured"
        )

    def search_gifs(self, request: SearchGifsRequest) -> SearchGifsResponse:
        """
        Search for GIFs using available APIs.

        Args:
            request: Search parameters including query and filters

        Returns:
            SearchGifsResponse with found GIFs and metadata
        """
        # Determine provider considering explicit request source and available keys
        provider = self._resolve_provider(request.source)

        if provider == GifSource.giphy:
            return self._search_giphy(request)
        if provider == GifSource.tenor:
            return self._search_tenor(request)
        raise ValueError("No GIF providers configured. Set GIPHY_API_KEY or TENOR_API_KEY.")

    def get_random_gif(self, request: GetRandomGifRequest) -> GifResult:
        """
        Get a random GIF based on optional tag.

        Args:
            request: Random GIF request with optional tag filter

        Returns:
            Random GIF result
        """
        provider = self._resolve_provider(request.source)

        if provider == GifSource.giphy:
            return self._get_random_giphy(request)
        if provider == GifSource.tenor:
            return self._get_random_tenor(request)
        raise ValueError("No GIF providers configured. Set GIPHY_API_KEY or TENOR_API_KEY.")

    def get_trending_gifs(
        self, request: GetTrendingGifsRequest
    ) -> SearchGifsResponse:
        """
        Get currently trending GIFs.

        Args:
            request: Trending GIFs request with time period filter

        Returns:
            Trending GIFs response
        """
        provider = self._resolve_provider(request.source)

        if provider == GifSource.giphy:
            return self._get_trending_giphy(request)
        if provider == GifSource.tenor:
            return self._get_trending_tenor(request)
        raise ValueError("No GIF providers configured. Set GIPHY_API_KEY or TENOR_API_KEY.")

    def format_for_slack(
        self, gif: GifResult, message: str = ""
    ) -> SlackGifMessage:
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
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}}
        ]

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

    def _resolve_provider(self, preferred: GifSource | str | None) -> GifSource:
        """Resolve which provider to use given preference and available API keys.

        Args:
            preferred: Optional preferred provider from the request.

        Returns:
            GifSource: The selected provider considering fallbacks.
        """
        # Accept raw strings and coerce to enum, raising on unsupported values
        if isinstance(preferred, str):
            try:
                preferred = GifSource(preferred)
            except Exception as exc:  # invalid provider value
                raise ValueError(f"Unsupported GIF provider: {preferred}") from exc
        # If preferred is giphy but no key, fallback to tenor/mock
        if preferred == GifSource.giphy:
            if self.giphy_api_key:
                return GifSource.giphy
            if self.tenor_api_key:
                return GifSource.tenor
            raise ValueError("Giphy requested but GIPHY_API_KEY is not set; no alternative provider available")

        # If preferred is tenor but no key, fallback to giphy/mock
        if preferred == GifSource.tenor:
            if self.tenor_api_key:
                return GifSource.tenor
            if self.giphy_api_key:
                return GifSource.giphy
            raise ValueError("Tenor requested but TENOR_API_KEY is not set; no alternative provider available")

        # No preference: choose by availability defaulting to mock
        if self.giphy_api_key:
            return GifSource.giphy
        if self.tenor_api_key:
            return GifSource.tenor
        raise ValueError("No GIF providers configured. Set GIPHY_API_KEY or TENOR_API_KEY.")

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
                size=(
                    int(gif_data["images"]["original"]["size"]) if gif_data["images"]["original"]["size"] else None
                ),
                source="giphy",
            )
            gifs.append(gif)

        return SearchGifsResponse(
            gifs=gifs,
            total_count=data.get("pagination", {}).get(
                "total_count", len(gifs) or 1
            ),
            query=request.query,
            pagination=data.get("pagination", {}),
        )

    def _search_tenor(self, request: SearchGifsRequest) -> SearchGifsResponse:
        """Search GIFs using Tenor API."""
        url = "https://tenor.googleapis.com/v2/search"
        params = {
            "key": self.tenor_api_key,
            "q": request.query,
            "limit": request.limit,
            "client_key": "agentcore_marketplace",
        }

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
                size=None,
                source="tenor",
            )
            gifs.append(gif)

        return SearchGifsResponse(
            gifs=gifs,
            total_count=1,
            query=request.query,
            pagination={"next": data.get("next")},
        )

    # mock search removed

    def _get_random_giphy(self, request: GetRandomGifRequest) -> GifResult:
        """Get random GIF from Giphy."""
        url = "https://api.giphy.com/v1/gifs/random"
        params = {
            "api_key": self.giphy_api_key,
            "tag": request.tag or "",
            "rating": request.rating,
        }

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
            size=(
                int(gif_data["images"]["original"]["size"]) if gif_data["images"]["original"]["size"] else None
            ),
            source="giphy",
        )

    def _get_random_tenor(self, request: GetRandomGifRequest) -> GifResult:
        """Get random GIF from Tenor."""
        # Tenor doesn't have a direct random endpoint, so we'll search and pick random
        search_request = SearchGifsRequest(
            query=request.tag or "random", limit=20, rating=request.rating
        )
        search_response = self._search_tenor(search_request)
        if search_response.gifs:
            return random.choice(search_response.gifs)
        raise ValueError("No Tenor GIFs found for the given tag")

    # random mock removed

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
                size=(
                    int(gif_data["images"]["original"]["size"]) if gif_data["images"]["original"]["size"] else None
                ),
                source="giphy",
            )
            gifs.append(gif)

        return SearchGifsResponse(
            gifs=gifs,
            total_count=len(gifs),
            query="trending",
            pagination={"limit": request.limit},
        )

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

    # trending mock removed
