import os
from unittest.mock import MagicMock, patch

from src.completion_notifier import lambda_handler


@patch("boto3.resource")
@patch("src.slack_blockkit.post_message_with_response")
def test_notifier_posts_reply_only(
    mock_post: MagicMock, mock_resource: MagicMock
) -> None:
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["TABLE_NAME"] = "tbl"
    os.environ["SLACK_BOT_TOKEN"] = "xoxb-test"

    # Mock table get_item to return slack metadata
    table = MagicMock()
    mock_resource.return_value.Table.return_value = table
    table.get_item.return_value = {
        "Item": {
            "request_id": "r1",
            "slack_channel": "C1",
            "slack_ts": "t1",
        }
    }

    event = {"request_id": "r1", "result": {"body": {"msg": "done"}}}
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200
    # Small payload should still post a single threaded reply
    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs.get("thread_ts") == "t1"


@patch("boto3.resource")
@patch("src.slack_blockkit.post_message_with_response")
def test_notifier_crafts_blocks_from_text(
    mock_post: MagicMock, mock_resource: MagicMock
) -> None:
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["TABLE_NAME"] = "tbl"
    os.environ["SLACK_BOT_TOKEN"] = "xoxb-test"

    table = MagicMock()
    mock_resource.return_value.Table.return_value = table
    table.get_item.return_value = {
        "Item": {
            "request_id": "r2",
            "slack_channel": "C2",
            "slack_ts": "t2",
        }
    }

    # Raw/markdown text only; notifier should craft blocks including header
    event = {"request_id": "r2", "result": {"body": "*Done*"}}
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200
    assert mock_post.called
    # Ensure reply called with blocks in kwargs
    assert mock_post.call_args.kwargs.get("thread_ts") == "t2"
    blocks = mock_post.call_args.kwargs.get("blocks")
    assert isinstance(blocks, list) and len(blocks) >= 2
    assert blocks[0]["type"] == "header"
    # Rich text is now used for content sections
    assert any(b["type"] == "rich_text" for b in blocks)


@patch("boto3.resource")
@patch("src.slack_blockkit.post_message_with_response")
def test_notifier_chunks_long_text_into_multiple_replies(
    mock_post: MagicMock, mock_resource: MagicMock
) -> None:
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["TABLE_NAME"] = "tbl"
    os.environ["SLACK_BOT_TOKEN"] = "xoxb-test"

    table = MagicMock()
    mock_resource.return_value.Table.return_value = table
    table.get_item.return_value = {
        "Item": {
            "request_id": "r3",
            "slack_channel": "C3",
            "slack_ts": "t3",
        }
    }

    # Create long text to force chunking (> 3100 chars)
    long_text = "Paragraph one.\n\n" + ("A" * 3100)
    event = {"request_id": "r3", "result": {"body": long_text}}
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200
    # All pages should be replies
    assert mock_post.called
    # Ensure continuation posts are threaded replies
    for call in mock_post.call_args_list:
        assert call.kwargs.get("thread_ts") == "t3"


@patch("boto3.resource")
def test_notifier_missing_request_id(mock_resource: MagicMock) -> None:
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["TABLE_NAME"] = "tbl"
    resp = lambda_handler({}, None)
    assert resp["body"]["skipped"] == "missing_request_id"
