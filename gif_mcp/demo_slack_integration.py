"""Demo script showing GIF MCP server integration with Slack.

This script demonstrates how the GIF MCP server can be used to:
1. Search for GIFs
2. Format them for Slack display
3. Generate the proper Slack API payload
"""

import json

from gif_mcp.models import GetRandomGifRequest, SearchGifsRequest
from gif_mcp.service import GifService


def demo_gif_search_and_slack_formatting():
    """Demonstrate GIF search and Slack formatting."""
    print("🎬 GIF MCP Server - Slack Integration Demo")
    print("=" * 60)

    service = GifService()

    # Demo 1: Search for GIFs and format for Slack
    print("\n📱 Demo 1: Search and Format for Slack")
    print("-" * 40)

    search_request = SearchGifsRequest(query="celebration", limit=1)
    search_result = service.search_gifs(search_request)

    if search_result.gifs:
        gif = search_result.gifs[0]
        print(f"Found GIF: {gif.title}")
        print(f"Source: {gif.source}")

        # Format for Slack
        slack_message = service.format_for_slack(
            gif, "🎉 Time to celebrate! Here's your GIF:"
        )

        print(f"\nSlack Message: {slack_message.text}")
        print(f"GIF URL: {slack_message.gif_url}")

        # Show the Slack blocks
        print(f"\nSlack Blocks ({len(slack_message.blocks)} blocks):")
        for i, block in enumerate(slack_message.blocks):
            print(f"  Block {i + 1}: {block['type']}")
            if block["type"] == "image":
                print(f"    Image: {block['image_url']}")

    # Demo 2: Random GIF for Slack
    print("\n🎲 Demo 2: Random GIF for Slack")
    print("-" * 40)

    random_request = GetRandomGifRequest(tag="funny", rating="g")
    random_gif = service.get_random_gif(random_request)

    slack_message = service.format_for_slack(
        random_gif, "😄 Here's a random funny GIF for you!"
    )

    print(f"Random GIF: {random_gif.title}")
    print(f"Slack Message: {slack_message.text}")

    # Demo 3: Complete Slack API payload
    print("\n📤 Demo 3: Complete Slack API Payload")
    print("-" * 40)

    # Simulate what would be sent to Slack
    slack_payload = {
        "channel": "#general",
        "text": slack_message.text,
        "blocks": slack_message.blocks,
    }

    print("Slack API Payload:")
    print(json.dumps(slack_payload, indent=2))

    # Demo 4: MCP Tool Response Format
    print("\n🔧 Demo 4: MCP Tool Response Format")
    print("-" * 40)

    # This is what the MCP tool would return
    mcp_response = slack_message.model_dump()
    print("MCP Tool Response (for AgentCore):")
    print(json.dumps(mcp_response, indent=2))

    print("\n" + "=" * 60)
    print("✅ Demo completed successfully!")
    print("\nTo use in production:")
    print("1. Set GIPHY_API_KEY or TENOR_API_KEY environment variables")
    print("2. The MCP server will return Slack-formatted responses")
    print("3. AgentCore can use the 'blocks' field for rich Slack display")
    print("4. GIFs will appear inline in Slack messages")


def demo_mcp_tool_responses():
    """Demonstrate the MCP tool responses that AgentCore would receive."""
    print("\n🤖 MCP Tool Response Demo")
    print("=" * 60)

    service = GifService()

    # Simulate MCP tool calls
    tools = [
        (
            "search_and_format_for_slack",
            {"query": "success", "message": "🚀 Mission accomplished!"},
        ),
        (
            "get_random_gif_for_slack",
            {"tag": "celebration", "message": "🎊 Party time!"},
        ),
        ("search_gifs", {"query": "coding", "limit": 3}),
    ]

    for tool_name, params in tools:
        print(f"\n🔧 Tool: {tool_name}")
        print(f"Parameters: {params}")

        if tool_name == "search_and_format_for_slack":
            # This would be the actual MCP tool call
            search_request = SearchGifsRequest(query=params["query"], limit=1)
            search_result = service.search_gifs(search_request)

            if search_result.gifs:
                gif = search_result.gifs[0]
                slack_message = service.format_for_slack(gif, params["message"])
                response = slack_message.model_dump()
            else:
                response = {"error": "No GIFs found"}

        elif tool_name == "get_random_gif_for_slack":
            random_request = GetRandomGifRequest(tag=params["tag"], rating="g")
            gif = service.get_random_gif(random_request)
            slack_message = service.format_for_slack(gif, params["message"])
            response = slack_message.model_dump()

        elif tool_name == "search_gifs":
            search_request = SearchGifsRequest(**params)
            result = service.search_gifs(search_request)
            response = result.model_dump()

        print(f"Response: {json.dumps(response, indent=2)}")


if __name__ == "__main__":
    demo_gif_search_and_slack_formatting()
    demo_mcp_tool_responses()
