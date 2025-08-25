"""Example usage of the GIF MCP Server.

This file demonstrates how to use the GIF MCP server tools
for searching, retrieving, and formatting GIFs for Slack.
"""

import asyncio

from gif_mcp.models import GetRandomGifRequest, SearchGifsRequest
from gif_mcp.service import GifService


async def example_gif_search():
    """Example of searching for GIFs."""
    print("=== GIF Search Example ===")

    service = GifService()

    # Search for GIFs
    request = SearchGifsRequest(query="happy", limit=3, rating="g")

    result = service.search_gifs(request)
    print(f"Found {len(result.gifs)} GIFs for '{result.query}'")

    for i, gif in enumerate(result.gifs, 1):
        print(f"\n{i}. {gif.title}")
        print(f"   Source: {gif.source}")
        print(f"   URL: {gif.url}")
        print(f"   Dimensions: {gif.width}x{gif.height}")
        if gif.size:
            print(f"   Size: {gif.size} bytes")


async def example_random_gif():
    """Example of getting a random GIF."""
    print("\n=== Random GIF Example ===")

    service = GifService()

    # Get random GIF
    request = GetRandomGifRequest(tag="funny", rating="g")
    gif = service.get_random_gif(request)

    print(f"Random GIF: {gif.title}")
    print(f"Source: {gif.source}")
    print(f"URL: {gif.url}")


async def example_slack_formatting():
    """Example of formatting GIFs for Slack."""
    print("\n=== Slack Formatting Example ===")

    service = GifService()

    # Search for a GIF
    search_request = SearchGifsRequest(query="celebration", limit=1)
    search_result = service.search_gifs(search_request)

    if search_result.gifs:
        gif = search_result.gifs[0]

        # Format for Slack
        slack_message = service.format_for_slack(gif, "🎉 Time to celebrate!")

        print(f"Slack Message: {slack_message.text}")
        print(f"GIF URL: {slack_message.gif_url}")
        print(f"GIF Title: {slack_message.gif_title}")
        print(f"Number of blocks: {len(slack_message.blocks)}")

        # Show the Slack blocks structure
        for i, block in enumerate(slack_message.blocks):
            print(f"\nBlock {i + 1}:")
            print(f"  Type: {block['type']}")
            if block["type"] == "section":
                print(f"  Text: {block['text']['text']}")
            elif block["type"] == "image":
                print(f"  Image URL: {block['image_url']}")
                print(f"  Alt Text: {block['alt_text']}")


async def example_trending_gifs():
    """Example of getting trending GIFs."""
    print("\n=== Trending GIFs Example ===")

    service = GifService()

    from gif_mcp.models import GetTrendingGifsRequest

    # Get trending GIFs
    request = GetTrendingGifsRequest(limit=2, rating="g")
    result = service.get_trending_gifs(request)

    print(f"Found {len(result.gifs)} trending GIFs")

    for i, gif in enumerate(result.gifs, 1):
        print(f"\n{i}. {gif.title}")
        print(f"   Source: {gif.source}")
        print(f"   URL: {gif.url}")


async def example_combined_workflow():
    """Example of a complete workflow: search, select, and format for Slack."""
    print("\n=== Combined Workflow Example ===")

    service = GifService()

    # 1. Search for GIFs
    print("1. Searching for GIFs...")
    search_request = SearchGifsRequest(query="success", limit=5)
    search_result = service.search_gifs(search_request)

    if not search_result.gifs:
        print("No GIFs found!")
        return

    # 2. Select the first GIF
    selected_gif = search_result.gifs[0]
    print(f"2. Selected: {selected_gif.title}")

    # 3. Format for Slack
    print("3. Formatting for Slack...")
    slack_message = service.format_for_slack(
        selected_gif, "🚀 Mission accomplished! Here's your success GIF:"
    )

    # 4. Display the result
    print("\nFinal Slack Message:")
    print(f"Text: {slack_message.text}")
    print(f"GIF: {slack_message.gif_url}")

    # 5. Show how to use in Slack API
    print("\nSlack API Payload:")
    slack_payload = {
        "channel": "#general",
        "text": slack_message.text,
        "blocks": slack_message.blocks,
    }
    print(f"Channel: {slack_payload['channel']}")
    print(f"Text: {slack_payload['text']}")
    print(f"Blocks: {len(slack_payload['blocks'])} blocks")


def main():
    """Run all examples."""
    print("GIF MCP Server Examples")
    print("=" * 50)

    # Run examples
    asyncio.run(example_gif_search())
    asyncio.run(example_random_gif())
    asyncio.run(example_slack_formatting())
    asyncio.run(example_trending_gifs())
    asyncio.run(example_combined_workflow())

    print("\n" + "=" * 50)
    print("Examples completed!")
    print("\nTo use with Slack:")
    print("1. Set GIPHY_API_KEY or TENOR_API_KEY environment variables")
    print("2. Use the Slack blocks format for rich display")
    print("3. The GIF will appear inline in Slack messages")


if __name__ == "__main__":
    main()
