"""Data models for GIF MCP Server."""

from pydantic import BaseModel, Field


class SearchGifsRequest(BaseModel):
    """Request model for searching GIFs."""

    query: str = Field(..., description="Search query for GIFs")
    limit: int = Field(
        default=10, ge=1, le=50, description="Maximum number of GIFs to return"
    )
    rating: str | None = Field(
        default="g", description="Content rating (g, pg, pg-13, r)"
    )
    language: str | None = Field(
        default="en", description="Language for search results"
    )
    offset: int = Field(
        default=0, ge=0, description="Number of results to skip for pagination"
    )


class GifResult(BaseModel):
    """Model for individual GIF search results."""

    id: str = Field(..., description="Unique identifier for the GIF")
    title: str = Field(..., description="Title or description of the GIF")
    url: str = Field(..., description="Direct URL to the GIF file")
    preview_url: str = Field(..., description="Preview/thumbnail URL")
    width: int = Field(..., description="Width of the GIF in pixels")
    height: int = Field(..., description="Height of the GIF in pixels")
    size: int | None = Field(None, description="File size in bytes")
    source: str = Field(
        ..., description="Source platform (e.g., 'giphy', 'tenor')"
    )


class SearchGifsResponse(BaseModel):
    """Response model for GIF search results."""

    gifs: list[GifResult] = Field(..., description="List of found GIFs")
    total_count: int = Field(
        ..., description="Total number of available results"
    )
    query: str = Field(..., description="Original search query")
    pagination: dict = Field(..., description="Pagination information")


class GetRandomGifRequest(BaseModel):
    """Request model for getting a random GIF."""

    tag: str | None = Field(None, description="Tag to filter random GIF by")
    rating: str | None = Field(default="g", description="Content rating")


class GetTrendingGifsRequest(BaseModel):
    """Request model for getting trending GIFs."""

    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of trending GIFs to return",
    )
    rating: str | None = Field(default="g", description="Content rating")
    time_period: str | None = Field(
        default="day",
        description="Time period for trending (day, week, month)",
    )


class SlackGifMessage(BaseModel):
    """Model for Slack-compatible GIF message format."""

    text: str = Field(..., description="Text message to accompany the GIF")
    gif_url: str = Field(..., description="URL of the GIF to display")
    gif_title: str = Field(..., description="Title/description of the GIF")
    blocks: list[dict] | None = Field(
        None, description="Slack blocks for rich formatting"
    )
