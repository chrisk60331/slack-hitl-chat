"""GIF MCP Server.

This module provides an MCP server for GIF operations including
searching, random GIFs, trending GIFs, and Slack formatting.
"""

import os
import sys

from fastmcp import FastMCP
from fastmcp.server.auth import BearerAuthProvider
from fastmcp.server.auth.providers.bearer import RSAKeyPair

# Add the gif_mcp directory to the path for local development
current_dir = os.path.dirname(os.path.abspath(__file__))
gif_mcp_dir = os.path.join(current_dir, "..")
sys.path.append(gif_mcp_dir)

from gif_mcp.models import (
    GetRandomGifRequest,
    GetTrendingGifsRequest,
    SearchGifsRequest,
)
from gif_mcp.service import GifService

# Generate a new key pair for development/testing
key_pair = RSAKeyPair.generate()

# Configure the auth provider with the public key (optional for stdio)
auth = BearerAuthProvider(
    public_key=key_pair.public_key,
    issuer="https://dev.example.com",
    audience="gif_mcp",
)

# Initialize MCP server
mcp = FastMCP(
    "GIF MCP Server",
    # auth=auth,  # Commented out for stdio transport
    dependencies=["gif_mcp@./gif_mcp"],
)

# Initialize service
gif_service = GifService()


@mcp.tool(
    name="search_gifs",
    description="Search for GIFs using various criteria and APIs.",
    tags=["gifs", "search", "media"],
)
def search_gifs(request: SearchGifsRequest) -> dict:
    """
    Search for GIFs using available APIs (Giphy, Tenor, or mock fallback).

    Args:
        request (SearchGifsRequest):
            query (str): Search query string for GIFs.
            limit (int, optional): Maximum number of GIFs to return (1-50).
            rating (str, optional): Content rating (g, pg, pg-13, r).
            language (str, optional): Language for search results.
            offset (int, optional): Number of results to skip for pagination.

    Returns:
        dict: Search results with GIF metadata and file information.
    """
    result = gif_service.search_gifs(request)
    return result.model_dump()


@mcp.tool(
    name="get_random_gif",
    description="Get a random GIF based on optional tag filter.",
    tags=["gifs", "random", "media"],
)
def get_random_gif(request: GetRandomGifRequest) -> dict:
    """
    Get a random GIF from available APIs.

    Args:
        request (GetRandomGifRequest):
            tag (str, optional): Tag to filter random GIF by.
            rating (str, optional): Content rating (g, pg, pg-13, r).

    Returns:
        dict: Random GIF result with metadata.
    """
    result = gif_service.get_random_gif(request)
    return result.model_dump()


@mcp.tool(
    name="get_trending_gifs",
    description="Get currently trending GIFs from popular platforms.",
    tags=["gifs", "trending", "media"],
)
def get_trending_gifs(request: GetTrendingGifsRequest) -> dict:
    """
    Get trending GIFs from available APIs.

    Args:
        request (GetTrendingGifsRequest):
            limit (int, optional): Maximum number of trending GIFs to return (1-50).
            rating (str, optional): Content rating (g, pg, pg-13, r).
            time_period (str, optional): Time period for trending (day, week, month).

    Returns:
        dict: Trending GIFs response with metadata.
    """
    result = gif_service.get_trending_gifs(request)
    return result.model_dump()


@mcp.tool(
    name="format_gif_for_slack",
    description="Format a GIF result for Slack display with rich blocks.",
    tags=["gifs", "slack", "formatting"],
)
def format_gif_for_slack(gif_data: dict, message: str = "") -> dict:
    """
    Format a GIF result for Slack display with rich formatting blocks.

    Args:
        gif_data (dict): GIF result data from search or random endpoints.
        message (str, optional): Custom text message to accompany the GIF.

    Returns:
        dict: Slack-formatted GIF message with blocks for rich display.
    """
    from gif_mcp.models import GifResult

    # Convert dict back to GifResult model
    gif = GifResult(**gif_data)
    result = gif_service.format_for_slack(gif, message)
    return result.model_dump()


@mcp.tool(
    name="search_and_format_for_slack",
    description="Search for GIFs and format them for Slack in one operation.",
    tags=["gifs", "search", "slack", "formatting"],
)
def search_and_format_for_slack(
    query: str, message: str = "", limit: int = 5
) -> dict:
    """
    Search for GIFs and format the first result for Slack display.

    Args:
        query (str): Search query for GIFs.
        message (str, optional): Custom text message to accompany the GIF.
        limit (int, optional): Maximum number of GIFs to search (1-10).

    Returns:
        dict: Slack-formatted GIF message with the first search result.
    """
    search_request = SearchGifsRequest(query=query, limit=limit)
    search_result = gif_service.search_gifs(search_request)

    if not search_result.gifs:
        return {
            "text": f"No GIFs found for '{query}'",
            "gif_url": "",
            "gif_title": "",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"No GIFs found for '{query}'",
                    },
                }
            ],
        }

    # Format the first result for Slack
    first_gif = search_result.gifs[0]
    result = gif_service.format_for_slack(first_gif, message)
    return result.model_dump()


@mcp.tool(
    name="get_random_gif_for_slack",
    description="Get a random GIF and format it for Slack display.",
    tags=["gifs", "random", "slack", "formatting"],
)
def get_random_gif_for_slack(
    tag: str = "", message: str = "", rating: str = "g"
) -> dict:
    """
    Get a random GIF and format it for Slack display.

    Args:
        tag (str, optional): Tag to filter random GIF by.
        message (str, optional): Custom text message to accompany the GIF.
        rating (str, optional): Content rating (g, pg, pg-13, r).

    Returns:
        dict: Slack-formatted random GIF message.
    """
    request = GetRandomGifRequest(tag=tag, rating=rating)
    gif = gif_service.get_random_gif(request)
    result = gif_service.format_for_slack(gif, message)
    return result.model_dump()


if __name__ == "__main__":
    mcp.run()
