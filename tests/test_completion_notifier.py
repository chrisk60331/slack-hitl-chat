import os
from unittest.mock import MagicMock, patch

from src.completion_notifier import lambda_handler


@patch("boto3.resource")
@patch("src.slack_lambda._slack_api")
def test_notifier_updates_slack(
    mock_slack_api: MagicMock, mock_resource: MagicMock
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
    mock_slack_api.assert_called_once()
    called_payload = mock_slack_api.call_args.args[2]
    assert called_payload["channel"] == "C1"
    assert called_payload["ts"] == "t1"


@patch("boto3.resource")
@patch("src.slack_lambda._slack_api")
def test_notifier_crafts_blocks_from_text(
    mock_slack_api: MagicMock, mock_resource: MagicMock
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
    called_payload = mock_slack_api.call_args.args[2]
    assert called_payload["channel"] == "C2"
    assert called_payload["ts"] == "t2"
    blocks = called_payload.get("blocks")
    assert isinstance(blocks, list) and len(blocks) >= 2
    assert blocks[0]["type"] == "header"
    assert any(b["type"] == "section" for b in blocks)


@patch("boto3.resource")
@patch("src.slack_lambda._slack_api")
def test_notifier_chunks_long_text_into_multiple_sections(
    mock_slack_api: MagicMock, mock_resource: MagicMock
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
    called_payload = mock_slack_api.call_args.args[2]
    assert called_payload["channel"] == "C3"
    assert called_payload["ts"] == "t3"
    blocks = called_payload.get("blocks")
    assert isinstance(blocks, list)
    # header + context + >= 2 sections
    section_blocks = [b for b in blocks if b.get("type") == "section"]
    assert len(section_blocks) >= 2


@patch("boto3.resource")
def test_notifier_missing_request_id(mock_resource: MagicMock) -> None:
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["TABLE_NAME"] = "tbl"
    resp = lambda_handler({}, None)
    assert resp["body"]["skipped"] == "missing_request_id"
