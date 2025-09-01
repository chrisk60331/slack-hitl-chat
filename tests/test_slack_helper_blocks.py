from src.slack_helper import build_thread_context


def test_build_thread_context_includes_block_only_bot_replies() -> None:
    bot_user_id = "U_BOT"
    messages = [
        {"user": "U1", "text": "hi"},
        {
            "user": bot_user_id,
            "text": "",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": "Title"}},
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": "*Request ID:*\nr1"},
                        {"type": "mrkdwn", "text": "*Requester:*\nuser@example.com"},
                    ],
                },
                {"type": "section", "text": {"type": "mrkdwn", "text": "Details here"}},
            ],
        },
    ]

    ctx = build_thread_context(messages, bot_user_id=bot_user_id, max_turns=10, max_chars=2000)
    # Should include both user line and assistant extracted from blocks
    assert "user: hi" in ctx
    assert "assistant: Title" in ctx or "assistant: Details here" in ctx


