import json
from unittest.mock import MagicMock, patch


def _approval_item(agent_prompt: str | None) -> dict:
    item = {
        "request_id": "r1",
        "requester": "user@example.com",
        "approver": "",
        "agent_prompt": agent_prompt or "",
        "proposed_action": "list s3 buckets",
        "approval_status": "allow",
        "slack_channel": "C1",
        "slack_ts": "1.0",
    }
    return item


@patch("src.execute_handler.get_approval_status")
@patch("src.execute_handler.invoke_mcp_client")
@patch("src.execute_handler.table")
def test_execute_handler_prepends_agent_prompt(
    mock_table: MagicMock, mock_invoke: MagicMock, mock_get_status: MagicMock
) -> None:
    from src.execute_handler import lambda_handler

    from src.policy import ApprovalOutcome
    mock_get_status.return_value = type(
        "A",
        (),
        {
            "proposed_action": "list s3 buckets",
            "requester": "user@example.com",
            "approval_status": ApprovalOutcome.ALLOW,
            "agent_prompt": "[Slack thread context]\nuser: hi\nassistant: hello",
        },
    )()

    mock_invoke.return_value = "done"
    mock_table.update_item.return_value = {}

    event = {"body": json.dumps({"request_id": "r1"})}
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200
    # Ensure combined query with context was passed
    assert mock_invoke.called
    args, kwargs = mock_invoke.call_args
    combined_query = args[0]
    assert combined_query.startswith("[Slack thread context]")
    assert "list s3 buckets" in combined_query


