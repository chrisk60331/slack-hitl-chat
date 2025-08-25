from __future__ import annotations

from unittest.mock import Mock, patch

from src.slack_helper import post_slack_webhook_message


def _fake_function_url() -> str:
    return "https://lambda-url"


@patch("src.slack_helper.requests.post")
def test_post_slack_webhook_message_basic(mock_post: Mock) -> None:
    mock_post.return_value.status_code = 200
    mock_post.return_value.text = "ok"

    content: dict[str, str] = {
        "title": "AgentCore HITL Pending Approval",
        "request_id": "req-1",
        "status": "approve",
        "requester": "alice",
        "approver": "",
        "agent_prompt": "Reset password",
        "proposed_action": "Reset password",
        "reason": "",
    }

    with patch.dict(
        "os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/X/Y"}
    ):
        ok = post_slack_webhook_message(content)
        assert ok is True
        mock_post.assert_called_once()


@patch("src.slack_helper.requests.post")
def test_post_slack_webhook_message_no_webhook(mock_post: Mock) -> None:
    content: dict[str, str] = {
        "title": "t",
        "request_id": "r",
        "status": "approve",
        "requester": "u",
        "approver": "",
        "agent_prompt": "p",
        "proposed_action": "pa",
        "reason": "",
    }

    with patch.dict("os.environ", {}, clear=True):
        ok = post_slack_webhook_message(content)
        assert ok is False
        mock_post.assert_not_called()


@patch("src.slack_helper.requests.post")
def test_post_slack_webhook_message_pending_includes_links(mock_post: Mock) -> None:
    mock_post.return_value.status_code = 200
    mock_post.return_value.text = "ok"

    content: dict[str, str] = {
        "title": "AgentCore HITL Pending Approval",
        "request_id": "req-2",
        "status": "pending",
        "requester": "alice",
        "approver": "",
        "agent_prompt": "Action",
        "proposed_action": "Do something",
        "reason": "",
    }

    with patch.dict(
        "os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/X/Y"}
    ):
        ok = post_slack_webhook_message(content, function_url_getter=_fake_function_url)
        assert ok is True
        args, kwargs = mock_post.call_args
        assert "json" in kwargs
        text = kwargs["json"]["text"]
        assert "Approve: https://lambda-url?request_id=req-2&action=approve" in text
        assert "Reject: https://lambda-url?request_id=req-2&action=reject" in text
