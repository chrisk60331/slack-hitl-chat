import json
from unittest.mock import MagicMock, patch


@patch("src.slack_lambda.get_secret_json")
@patch("src.slack_lambda.get_approval_table")
@patch("src.slack_lambda.handle_new_approval_request")
@patch("src.slack_lambda.get_bot_user_id")
@patch("src.slack_lambda.fetch_thread_messages")
@patch("src.slack_lambda.build_thread_context")
def test_events_handler_includes_thread_context_in_new_request(
    mock_build_ctx: MagicMock,
    mock_fetch: MagicMock,
    mock_get_bot: MagicMock,
    mock_handle_new: MagicMock,
    mock_get_table: MagicMock,
    mock_get_secret: MagicMock,
) -> None:
    from src.slack_lambda import events_handler

    mock_get_secret.return_value = {"bot_token": "xoxb-test"}
    # No existing item
    table = MagicMock()
    table.get_item.return_value = {"Item": None}
    mock_get_table.return_value = table

    mock_get_bot.return_value = "U_BOT"
    mock_fetch.return_value = [
        {"user": "U1", "text": "hi"},
        {"bot_id": "B1", "text": "hello"},
    ]
    mock_build_ctx.return_value = "user: hi\nassistant: hello"

    mock_handle_new.return_value = {"body": {"request_id": "rid"}}

    event = {
        "headers": {},
        "body": json.dumps(
            {
                "type": "event_callback",
                "event": {
                    "type": "message",
                    "channel": "C1",
                    "ts": "1.0",
                    "text": "do it",
                },
            }
        ),
    }

    resp = events_handler(event, None)
    assert resp["statusCode"] == 200

    # Ensure we created an approval request with enriched agent_prompt
    assert mock_handle_new.called
    payload = mock_handle_new.call_args.args[0]
    assert payload["slack_channel"] == "C1"
    assert payload["slack_ts"] == "1.0"
    assert payload["proposed_action"] == "do it"
    assert payload["agent_prompt"].startswith("[Slack thread context]")


