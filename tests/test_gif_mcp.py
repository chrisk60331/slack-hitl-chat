"""Tests for GIF MCP Server."""

from unittest.mock import Mock, patch

import pytest

from gif_mcp.models import (
    GetRandomGifRequest,
    GifResult,
    GifSource,
    SearchGifsRequest,
)
from gif_mcp.service import GifService


class TestGifResult:
    """Test GifResult model."""

    def test_gif_result_creation(self):
        """Test creating a GifResult instance."""
        gif = GifResult(
            id="test_id",
            title="Test GIF",
            url="https://example.com/test.gif",
            preview_url="https://example.com/preview.gif",
            width=480,
            height=270,
            size=1024000,
            source="test",
        )

        assert gif.id == "test_id"
        assert gif.title == "Test GIF"
        assert gif.url == "https://example.com/test.gif"
        assert gif.width == 480
        assert gif.height == 270
        assert gif.source == "test"

    def test_gif_result_optional_fields(self):
        """Test GifResult with optional fields."""
        gif = GifResult(
            id="test_id",
            title="Test GIF",
            url="https://example.com/test.gif",
            preview_url="https://example.com/preview.gif",
            width=480,
            height=270,
            source="test",
        )

        assert gif.size is None


class TestSearchGifsRequest:
    """Test SearchGifsRequest model."""

    def test_search_request_creation(self):
        """Test creating a SearchGifsRequest instance."""
        request = SearchGifsRequest(query="test query")

        assert request.query == "test query"
        assert request.limit == 10  # default
        assert request.rating == "g"  # default
        assert request.language == "en"  # default
        assert request.offset == 0  # default

    def test_search_request_custom_values(self):
        """Test SearchGifsRequest with custom values."""
        request = SearchGifsRequest(
            query="custom query",
            limit=20,
            rating="pg",
            language="es",
            offset=5,
        )

        assert request.query == "custom query"
        assert request.limit == 20
        assert request.rating == "pg"
        assert request.language == "es"
        assert request.offset == 5


class TestGifService:
    """Test GifService class."""

    @pytest.fixture
    def service(self):
        """Create a GifService instance for testing."""
        return GifService()

    @pytest.fixture
    def mock_giphy_response(self):
        """Mock Giphy API response."""
        return {
            "data": [
                {
                    "id": "giphy_1",
                    "title": "Giphy Test GIF 1",
                    "images": {
                        "original": {
                            "url": "https://media.giphy.com/media/test1.gif",
                            "width": "480",
                            "height": "270",
                            "size": "1024000",
                        },
                        "preview_gif": {
                            "url": "https://media.giphy.com/media/test1_preview.gif"
                        },
                    },
                },
                {
                    "id": "giphy_2",
                    "title": "Giphy Test GIF 2",
                    "images": {
                        "original": {
                            "url": "https://media.giphy.com/media/test2.gif",
                            "width": "480",
                            "height": "270",
                            "size": "2048000",
                        },
                        "preview_gif": {
                            "url": "https://media.giphy.com/media/test2_preview.gif"
                        },
                    },
                },
            ],
            "pagination": {"total_count": 2, "count": 2, "offset": 0},
        }

    @pytest.fixture
    def mock_tenor_response(self):
        """Mock Tenor API response."""
        return {
            "results": [
                {
                    "id": "tenor_1",
                    "title": "Tenor Test GIF 1",
                    "media_formats": {
                        "gif": {
                            "url": "https://tenor.com/view/test1.gif",
                            "dims": [480, 270],
                        },
                        "tinygif": {
                            "url": "https://tenor.com/view/test1_tiny.gif"
                        },
                    },
                },
                {
                    "id": "tenor_2",
                    "title": "Tenor Test GIF 2",
                    "media_formats": {
                        "gif": {
                            "url": "https://tenor.com/view/test2.gif",
                            "dims": [480, 270],
                        },
                        "tinygif": {
                            "url": "https://tenor.com/view/test2_tiny.gif"
                        },
                    },
                },
            ],
            "next": "next_cursor=20",
        }

    def test_service_initialization(self, service):
        """Test GifService initialization."""
        assert hasattr(service, "giphy_api_key")
        assert hasattr(service, "tenor_api_key")
        assert hasattr(service, "default_source")

    @patch.dict("os.environ", {"GIPHY_API_KEY": "test_key"})
    def test_service_with_giphy_key(self):
        """Test GifService with Giphy API key."""
        service = GifService()
        assert service.default_source == "giphy"

    @patch.dict("os.environ", {"TENOR_API_KEY": "test_key"})
    def test_service_with_tenor_key(self):
        """Test GifService with Tenor API key."""
        service = GifService()
        assert service.default_source == "tenor"

    def test_service_without_keys(self, service):
        """Service default source indicates unconfigured when no keys."""
        assert service.default_source == "unconfigured"

    @patch("requests.get")
    def test_search_giphy_success(
        self, mock_get, service, mock_giphy_response
    ):
        """Test successful Giphy search."""
        mock_response = Mock()
        mock_response.json.return_value = mock_giphy_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        # Set Giphy API key
        service.giphy_api_key = "test_key"

        request = SearchGifsRequest(query="test")
        result = service.search_gifs(request)

        assert len(result.gifs) == 2
        assert result.gifs[0].source == "giphy"
        assert result.gifs[0].id == "giphy_1"
        assert result.total_count == 2

    @patch("requests.get")
    def test_search_giphy_error_raises(self, mock_get, service):
        """Giphy search error propagates."""
        mock_get.side_effect = Exception("API Error")

        service.giphy_api_key = "test_key"

        request = SearchGifsRequest(query="test")
        with pytest.raises(Exception):
            service.search_gifs(request)

    @patch("requests.get")
    def test_search_tenor_success(
        self, mock_get, service, mock_tenor_response
    ):
        """Test successful Tenor search."""
        mock_response = Mock()
        mock_response.json.return_value = mock_tenor_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        # Set Tenor API key
        service.tenor_api_key = "test_key"
        service.giphy_api_key = None

        request = SearchGifsRequest(query="test")
        result = service.search_gifs(request)

        assert len(result.gifs) == 2
        assert result.gifs[0].source == "tenor"
        assert result.gifs[0].id == "tenor_1"

    def test_search_without_keys_raises(self, service):
        """No providers configured raises error."""
        service.giphy_api_key = None
        service.tenor_api_key = None
        request = SearchGifsRequest(query="test query")
        with pytest.raises(ValueError):
            service.search_gifs(request)
    @patch("requests.get")
    def test_force_tenor_without_key_raises(self, mock_get, service):
        """Explicit tenor source without key raises."""
        service.tenor_api_key = None
        service.giphy_api_key = None

        request = SearchGifsRequest(query="test", source=GifSource.tenor)
        with pytest.raises(ValueError):
            service.search_gifs(request)

    @patch("requests.get")
    def test_force_giphy_with_key(self, mock_get, service, mock_giphy_response):
        """Explicit giphy source uses giphy when key present."""
        mock_response = Mock()
        mock_response.json.return_value = mock_giphy_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        service.giphy_api_key = "test_key"
        service.tenor_api_key = None

        request = SearchGifsRequest(query="test", source=GifSource.giphy)
        result = service.search_gifs(request)

        assert len(result.gifs) == 2
        assert result.gifs[0].source == "giphy"

    @patch("requests.get")
    def test_force_mock_source_removed(self, mock_get, service):
        """Mock provider removed; using it should fail type or resolution."""
        service.giphy_api_key = "test_key"
        with pytest.raises(ValueError):
            # Bypass type system by casting; service should still raise
            service._resolve_provider("mock")

    @patch("requests.get")
    def test_get_random_giphy_success(self, mock_get, service):
        """Test successful random Giphy GIF."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "id": "random_giphy",
                "title": "Random Giphy GIF",
                "images": {
                    "original": {
                        "url": "https://media.giphy.com/media/random.gif",
                        "width": "480",
                        "height": "270",
                        "size": "1024000",
                    },
                    "preview_gif": {
                        "url": "https://media.giphy.com/media/random_preview.gif"
                    },
                },
            }
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        # Set Giphy API key
        service.giphy_api_key = "test_key"

        request = GetRandomGifRequest(tag="test")
        result = service.get_random_gif(request)

        assert result.source == "giphy"
        assert result.id == "random_giphy"

    def test_get_random_without_keys_raises(self, service):
        """Random without providers raises error."""
        service.giphy_api_key = None
        service.tenor_api_key = None
        with pytest.raises(ValueError):
            service.get_random_gif(GetRandomGifRequest(tag="x"))

    def test_format_for_slack(self, service):
        """Test Slack formatting."""
        gif = GifResult(
            id="test_id",
            title="Test GIF",
            url="https://example.com/test.gif",
            preview_url="https://example.com/preview.gif",
            width=480,
            height=270,
            source="test",
        )

        result = service.format_for_slack(gif, "Custom message")

        assert result.text == "Custom message"
        assert result.gif_url == "https://example.com/test.gif"
        assert result.gif_title == "Test GIF"
        assert len(result.blocks) == 2
        assert result.blocks[0]["type"] == "section"
        assert result.blocks[1]["type"] == "image"

    def test_format_for_slack_default_message(self, service):
        """Test Slack formatting with default message."""
        gif = GifResult(
            id="test_id",
            title="Test GIF",
            url="https://example.com/test.gif",
            preview_url="https://example.com/preview.gif",
            width=480,
            height=270,
            source="test",
        )

        result = service.format_for_slack(gif)

        assert result.text == "Here's a GIF: Test GIF"
        assert result.gif_url == "https://example.com/test.gif"


class TestIntegration:
    """Integration tests for the GIF MCP system."""

    @patch("requests.get")
    def test_end_to_end_search_and_format(self, mock_get):
        """Test end-to-end search and Slack formatting (with mocked provider)."""
        # Configure fake Giphy key and response
        service = GifService()
        service.giphy_api_key = "test_key"
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "giphy_1",
                    "title": "Giphy Test GIF 1",
                    "images": {
                        "original": {
                            "url": "https://media.giphy.com/media/test1.gif",
                            "width": "480",
                            "height": "270",
                            "size": "1024000",
                        },
                        "preview_gif": {
                            "url": "https://media.giphy.com/media/test1_preview.gif"
                        },
                    },
                }
            ],
            "pagination": {"total_count": 1, "count": 1, "offset": 0},
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        # Search for GIFs
        search_request = SearchGifsRequest(query="test", limit=1)
        search_result = service.search_gifs(search_request)

        assert len(search_result.gifs) > 0

        # Format for Slack
        gif = search_result.gifs[0]
        slack_message = service.format_for_slack(gif, "Test message")

        assert slack_message.text == "Test message"
        assert slack_message.gif_url == gif.url
        assert slack_message.blocks is not None

    def test_provider_required_when_no_keys(self):
        """Without keys, operations must fail clearly."""
        service = GifService()
        service.giphy_api_key = None
        service.tenor_api_key = None
        with pytest.raises(ValueError):
            service.search_gifs(SearchGifsRequest(query="x"))


if __name__ == "__main__":
    pytest.main([__file__])
