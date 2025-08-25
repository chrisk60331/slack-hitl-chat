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
def test_notifier_missing_request_id(mock_resource: MagicMock) -> None:
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["TABLE_NAME"] = "tbl"
    resp = lambda_handler({}, None)
    assert resp["body"]["skipped"] == "missing_request_id"
