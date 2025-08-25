"""Test script to verify Slack formatting for GIFs."""

import json

from gif_mcp.models import GifResult
from gif_mcp.service import GifService


def test_slack_formatting():
    """Test Slack formatting with a sample GIF."""

    # Create a sample GIF result
    gif = GifResult(
        id="test_gif_123",
        title="Test Funny GIF",
        url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif",
        preview_url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif",
        width=480,
        height=270,
        size=1024000,
        source="test",
    )

    # Test the service
    service = GifService()

    # Format for Slack
    slack_message = service.format_for_slack(gif, "🎉 Here's a funny GIF for you!")

    print("=== Slack Message Format ===")
    print(f"Text: {slack_message.text}")
    print(f"GIF URL: {slack_message.gif_url}")
    print(f"GIF Title: {slack_message.gif_title}")

    print("\n=== Slack Blocks ===")
    for i, block in enumerate(slack_message.blocks):
        print(f"\nBlock {i + 1}:")
        print(f"  Type: {block['type']}")
        if block["type"] == "section":
            print(f"  Text: {block['text']['text']}")
        elif block["type"] == "image":
            print(f"  Image URL: {block['image_url']}")
            print(f"  Alt Text: {block['alt_text']}")
            print(f"  Title: {block['title']['text']}")

    print("\n=== JSON Payload for Slack API ===")
    slack_payload = {
        "channel": "#test-channel",
        "text": slack_message.text,
        "blocks": slack_message.blocks,
    }
    print(json.dumps(slack_payload, indent=2))

    print("\n=== Testing MCP Tool Response ===")
    # Simulate what the MCP tool would return
    mcp_response = slack_message.model_dump()
    print("MCP Tool Response:")
    print(json.dumps(mcp_response, indent=2))

    # Test the blocks structure
    print("\n=== Blocks Validation ===")
    if slack_message.blocks:
        print("✅ Blocks generated successfully")
        image_blocks = [b for b in slack_message.blocks if b["type"] == "image"]
        if image_blocks:
            print(f"✅ Found {len(image_blocks)} image block(s)")
            for block in image_blocks:
                print(f"   - Image URL: {block['image_url']}")
                print(f"   - Alt Text: {block['alt_text']}")
        else:
            print("❌ No image blocks found")
    else:
        print("❌ No blocks generated")


if __name__ == "__main__":
    test_slack_formatting()
