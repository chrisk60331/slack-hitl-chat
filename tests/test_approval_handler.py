"""
Unit tests for the approval_handler module.

Tests the ApprovalItem Pydantic model and related functionality.
"""

import json
from unittest.mock import Mock, patch

import boto3
import pytest
from moto import mock_aws

from src.approval_handler import (
    ApprovalDecision,
    ApprovalItem,
    _extract_decision_data,
    _handle_approval_decision,
    _is_approval_decision,
    compute_request_id_from_action,
    get_approval_status,
    lambda_handler,
    send_notifications,
)


class TestApprovalItem:
    """Test cases for the ApprovalItem Pydantic model."""

    def test_approval_item_creation_with_defaults(self) -> None:
        """Test ApprovalItem creation with default values."""
        item = ApprovalItem()

        assert isinstance(item.request_id, str)
        assert len(item.request_id) > 0
        assert item.requester == ""
        assert item.approver == ""
        assert item.agent_prompt == ""
        assert item.proposed_action == ""
        assert item.reason == ""
        assert item.approval_status == "pending"
        assert isinstance(item.timestamp, str)

    def test_approval_item_creation_with_values(self) -> None:
        """Test ApprovalItem creation with provided values."""
        test_data = {
            "request_id": "test-123",
            "requester": "test_user",
            "approver": "admin_user",
            "agent_prompt": "Test prompt",
            "proposed_action": "Test action",
            "reason": "Test reason",
            "approval_status": "approved",
            "timestamp": "2024-01-01T00:00:00Z",
        }

        item = ApprovalItem(**test_data)

        assert item.request_id == "test-123"
        assert item.requester == "test_user"
        assert item.approver == "admin_user"
        assert item.agent_prompt == "Test prompt"
        assert item.proposed_action == "Test action"
        assert item.reason == "Test reason"
        assert item.approval_status == "approved"
        assert item.timestamp == "2024-01-01T00:00:00Z"

    def test_to_dynamodb_item(self) -> None:
        """Test conversion to DynamoDB item format."""
        test_data = {
            "request_id": "test-123",
            "requester": "test_user",
            "approval_status": "approved",
        }

        item = ApprovalItem(**test_data)
        dynamodb_item = item.to_dynamodb_item()

        assert isinstance(dynamodb_item, dict)
        assert dynamodb_item["request_id"] == "test-123"
        assert dynamodb_item["requester"] == "test_user"
        assert dynamodb_item["approval_status"] == "approved"
        assert "timestamp" in dynamodb_item

    def test_from_dynamodb_item(self) -> None:
        """Test creation from DynamoDB item."""
        dynamodb_data = {
            "request_id": "test-123",
            "requester": "test_user",
            "approver": "admin_user",
            "agent_prompt": "Test prompt",
            "proposed_action": "Test action",
            "reason": "Test reason",
            "approval_status": "approved",
            "timestamp": "2024-01-01T00:00:00Z",
        }

        item = ApprovalItem.from_dynamodb_item(dynamodb_data)

        assert isinstance(item, ApprovalItem)
        assert item.request_id == "test-123"
        assert item.requester == "test_user"
        assert item.approval_status == "approved"

    def test_unique_request_ids(self) -> None:
        """Test that default request_ids are unique."""
        item1 = ApprovalItem()
        item2 = ApprovalItem()

        assert item1.request_id != item2.request_id


class TestDeterministicRequestId:
    """Tests for deterministic request_id hashing from proposed action."""

    def test_compute_request_id_from_action_deterministic(self) -> None:
        a = "Reset password for bob"
        b = "Reset password for bob"
        c = "Reset password for alice"
        ra1 = compute_request_id_from_action(a)
        ra2 = compute_request_id_from_action(b)
        rc = compute_request_id_from_action(c)
        assert ra1 == ra2
        assert ra1 != rc
        assert isinstance(ra1, str)
        assert len(ra1) == 64  # sha256 hex digest length


class TestApprovalDecision:
    """Test cases for the ApprovalDecision Pydantic model."""

    def test_approval_decision_creation_valid(self) -> None:
        """Test ApprovalDecision creation with valid data."""
        decision_data = {
            "request_id": "test-123",
            "action": "approve",
            "approver": "admin_user",
            "reason": "Looks good",
        }

        decision = ApprovalDecision(**decision_data)

        assert decision.request_id == "test-123"
        assert decision.action == "approve"
        assert decision.approver == "admin_user"
        assert decision.reason == "Looks good"

    def test_approval_decision_reject_action(self) -> None:
        """Test ApprovalDecision with reject action."""
        decision_data = {
            "request_id": "test-123",
            "action": "reject",
            "reason": "Not safe",
        }

        decision = ApprovalDecision(**decision_data)

        assert decision.request_id == "test-123"
        assert decision.action == "reject"
        assert decision.approver == ""
        assert decision.reason == "Not safe"

    def test_approval_decision_invalid_action(self) -> None:
        """Test ApprovalDecision with invalid action."""
        decision_data = {"request_id": "test-123", "action": "invalid_action"}

        with pytest.raises(ValueError):
            ApprovalDecision(**decision_data)

    def test_approval_decision_missing_request_id(self) -> None:
        """Test ApprovalDecision without request_id."""
        decision_data = {"action": "approve"}

        with pytest.raises(ValueError):
            ApprovalDecision(**decision_data)


class TestApprovalDecisionHandling:
    """Test cases for approval decision handling functions."""

    def test_is_approval_decision_with_body_dict(self) -> None:
        """Test _is_approval_decision with dict body."""
        event = {"body": {"request_id": "test-123", "action": "approve"}}

        assert _is_approval_decision(event) is True

    def test_is_approval_decision_with_body_string(self) -> None:
        """Test _is_approval_decision with JSON string body."""
        event = {"body": json.dumps({"request_id": "test-123", "action": "reject"})}

        assert _is_approval_decision(event) is True

    def test_is_approval_decision_with_query_params(self) -> None:
        """Test _is_approval_decision with query parameters."""
        event = {
            "queryStringParameters": {"request_id": "test-123", "action": "approve"}
        }

        assert _is_approval_decision(event) is True

    def test_is_approval_decision_false(self) -> None:
        """Test _is_approval_decision returns False for non-decision events."""
        event = {"requester": "test_user", "agent_prompt": "Test prompt"}

        assert _is_approval_decision(event) is False

    def test_extract_decision_data_from_dict_body(self) -> None:
        """Test _extract_decision_data from dict body."""
        event = {
            "body": {"request_id": "test-123", "action": "approve", "approver": "admin"}
        }

        data = _extract_decision_data(event)

        assert data["request_id"] == "test-123"
        assert data["action"] == "approve"
        assert data["approver"] == "admin"

    def test_extract_decision_data_from_string_body(self) -> None:
        """Test _extract_decision_data from JSON string body."""
        event = {
            "body": json.dumps(
                {"request_id": "test-123", "action": "reject", "reason": "Not safe"}
            )
        }

        data = _extract_decision_data(event)

        assert data["request_id"] == "test-123"
        assert data["action"] == "reject"
        assert data["reason"] == "Not safe"

    def test_extract_decision_data_from_query_params(self) -> None:
        """Test _extract_decision_data from query parameters."""
        event = {
            "queryStringParameters": {
                "request_id": "test-123",
                "action": "approve",
                "approver": "admin",
                "reason": "Approved via link",
            }
        }

        data = _extract_decision_data(event)

        assert data["request_id"] == "test-123"
        assert data["action"] == "approve"
        assert data["approver"] == "admin"
        assert data["reason"] == "Approved via link"

    def test_extract_decision_data_invalid(self) -> None:
        """Test _extract_decision_data with invalid event."""
        event = {"body": "invalid json"}

        with pytest.raises(ValueError, match="No valid decision data found"):
            _extract_decision_data(event)


class TestHandleApprovalDecision:
    """Test cases for the _handle_approval_decision function."""

    @mock_aws
    @patch("src.approval_handler.TABLE_NAME", "test-table")
    @patch("src.approval_handler.send_notifications")
    def test_handle_approval_decision_success(
        self, mock_send_notifications: Mock
    ) -> None:
        """Test successful approval decision handling."""
        # Setup mock DynamoDB
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="test-table",
            KeySchema=[{"AttributeName": "request_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "request_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Insert test approval item
        test_item = {
            "request_id": "test-123",
            "requester": "test_user",
            "approval_status": "pending",
            "agent_prompt": "Test prompt",
            "proposed_action": "Test action",
            "reason": "Initial reason",
            "approver": "",
            "timestamp": "2024-01-01T00:00:00Z",
        }
        table.put_item(Item=test_item)

        # Test event
        event = {
            "body": {
                "request_id": "test-123",
                "action": "approve",
                "approver": "admin_user",
                "reason": "Approved by admin",
            }
        }

        with patch("src.approval_handler.table", table):
            result = _handle_approval_decision(event)

        # Verify response
        assert result["statusCode"] == 200
        assert result["body"]["request_id"] == "test-123"
        assert result["body"]["status"] == "approve"
        assert result["body"]["approver"] == "admin_user"
        assert "approve successfully" in result["body"]["message"]

        # Verify DynamoDB was updated
        response = table.get_item(Key={"request_id": "test-123"})
        updated_item = response["Item"]
        assert updated_item["approval_status"] == "approve"
        assert updated_item["approver"] == "admin_user"
        assert updated_item["reason"] == "Approved by admin"

        # Verify notification was sent
        mock_send_notifications.assert_called_once()

    @mock_aws
    @patch("src.approval_handler.TABLE_NAME", "test-table")
    def test_handle_approval_decision_not_found(self) -> None:
        """Test approval decision with non-existent request ID."""
        # Setup mock DynamoDB
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="test-table",
            KeySchema=[{"AttributeName": "request_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "request_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        event = {"body": {"request_id": "nonexistent-123", "action": "approve"}}

        with patch("src.approval_handler.table", table):
            with pytest.raises(
                ValueError, match="Request ID nonexistent-123 not found"
            ):
                _handle_approval_decision(event)


class TestLambdaHandler:
    """Test cases for the main lambda_handler function."""

    @mock_aws
    @patch("src.approval_handler.TABLE_NAME", "test-table")
    @patch("src.approval_handler.send_notifications")
    def test_lambda_handler_approval_decision(
        self, mock_send_notifications: Mock
    ) -> None:
        """Test lambda_handler with approval decision."""
        # Setup mock DynamoDB
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="test-table",
            KeySchema=[{"AttributeName": "request_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "request_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Insert test approval item
        test_item = {
            "request_id": "test-123",
            "requester": "test_user",
            "approval_status": "pending",
            "agent_prompt": "Test prompt",
            "proposed_action": "Test action",
            "reason": "",
            "approver": "",
            "timestamp": "2024-01-01T00:00:00Z",
        }
        table.put_item(Item=test_item)

        # Test approval decision event
        event = {
            "httpMethod": "POST",
            "body": json.dumps(
                {
                    "request_id": "test-123",
                    "action": "reject",
                    "approver": "admin_user",
                    "reason": "Security concerns",
                }
            ),
        }

        with patch("src.approval_handler.table", table):
            result = lambda_handler(event, {})

        assert result["statusCode"] == 200
        assert result["body"]["status"] == "reject"
        assert result["body"]["approver"] == "admin_user"

    @mock_aws
    @patch("src.approval_handler.TABLE_NAME", "test-table")
    @patch("src.approval_handler.send_notifications")
    def test_lambda_handler_new_request_dedup_by_action(
        self, mock_send_notifications: Mock
    ) -> None:
        """Second identical proposed_action should reuse the same request_id and not notify."""
        # Setup mock DynamoDB
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="test-table",
            KeySchema=[{"AttributeName": "request_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "request_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        event = {
            "requester": "test_user",
            "agent_prompt": "Test prompt",
            "proposed_action": "Reset password for bob",
            "reason": "Test reason",
        }

        mock_send_notifications.return_value = True

        with patch("src.approval_handler.table", table):
            res1 = lambda_handler(event, {})
            res2 = lambda_handler(event, {})

        assert res1["statusCode"] == 200
        assert res2["statusCode"] == 200
        rid1 = res1["body"]["request_id"]
        rid2 = res2["body"]["request_id"]
        assert rid1 == rid2
        assert res1["body"]["notification_sent"] is True
        assert res2["body"]["notification_sent"] is False
        assert mock_send_notifications.call_count == 1

        # Only one item stored
        with patch("src.approval_handler.table", table):
            scan = table.scan()
        assert len(scan.get("Items", [])) == 1

    @mock_aws
    @patch("src.approval_handler.TABLE_NAME", "test-table")
    @patch("src.approval_handler.send_notifications")
    def test_lambda_handler_new_request(self, mock_send_notifications: Mock) -> None:
        """Test lambda_handler with new approval request."""
        # Setup mock DynamoDB
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="test-table",
            KeySchema=[{"AttributeName": "request_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "request_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        event = {
            "requester": "test_user",
            "agent_prompt": "Test prompt",
            "proposed_action": "Test action",
            "reason": "Test reason",
        }

        mock_send_notifications.return_value = True

        with patch("src.approval_handler.table", table):
            result = lambda_handler(event, {})

        assert result["statusCode"] == 200
        assert "request_id" in result["body"]
        assert result["body"]["notification_sent"] is True

    def test_lambda_handler_error(self) -> None:
        """Test lambda_handler error handling."""
        event = {"body": "invalid json that will cause an error"}

        with patch(
            "src.approval_handler._extract_decision_data",
            side_effect=Exception("Test error"),
        ):
            result = lambda_handler(event, {})

        assert result["statusCode"] == 500
        error_body = json.loads(result["body"])
        assert error_body["error"] == "operation failed"
        assert "Test error" in error_body["details"]


class TestGetApprovalStatus:
    """Test cases for the get_approval_status function."""

    @mock_aws
    @patch("src.approval_handler.TABLE_NAME", "test-table")
    def test_get_approval_status_found(self) -> None:
        """Test retrieving existing approval status."""
        # Setup mock DynamoDB
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="test-table",
            KeySchema=[{"AttributeName": "request_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "request_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Insert test data
        test_data = {
            "request_id": "test-123",
            "requester": "test_user",
            "approval_status": "approved",
        }
        table.put_item(Item=test_data)

        # Test the function
        with patch("src.approval_handler.table", table):
            result = get_approval_status("test-123")

        assert result is not None
        assert isinstance(result, ApprovalItem)
        assert result.request_id == "test-123"
        assert result.requester == "test_user"
        assert result.approval_status == "approved"

    @mock_aws
    @patch("src.approval_handler.TABLE_NAME", "test-table")
    def test_get_approval_status_not_found(self) -> None:
        """Test retrieving non-existent approval status."""
        # Setup mock DynamoDB
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="test-table",
            KeySchema=[{"AttributeName": "request_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "request_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Test the function
        with patch("src.approval_handler.table", table):
            result = get_approval_status("nonexistent-123")

        assert result is None


class TestSendNotifications:
    """Test cases for the send_notifications function."""

    @patch("src.approval_handler.sns")
    @patch("src.approval_handler.SNS_TOPIC_ARN", "test-topic-arn")
    @patch(
        "src.approval_handler.LAMBDA_FUNCTION_URL",
        "https://test.lambda-url.us-east-1.on.aws/",
    )
    def test_send_notifications_pending_with_links(self, mock_sns: Mock) -> None:
        """Test sending pending notification with approval links."""
        mock_sns.publish.return_value = {"MessageId": "test-message-id"}

        result = send_notifications(
            request_id="test-123",
            action="pending",
            requester="test_user",
            approver="",
            agent_prompt="Test prompt",
            proposed_action="Test action",
            reason="Test reason",
        )

        assert result is True
        mock_sns.publish.assert_called_once()
        call_args = mock_sns.publish.call_args
        assert call_args[1]["TopicArn"] == "test-topic-arn"
        assert "pending" in call_args[1]["Subject"]

        # Check that approval links are included in the message
        message = call_args[1]["Message"]
        assert "APPROVAL ACTIONS:" in message
        assert (
            "https://test.lambda-url.us-east-1.on.aws/?request_id=test-123&action=approve"
            in message
        )
        assert (
            "https://test.lambda-url.us-east-1.on.aws/?request_id=test-123&action=reject"
            in message
        )

    @patch("src.approval_handler.sns")
    @patch("src.approval_handler.SNS_TOPIC_ARN", "test-topic-arn")
    def test_send_notifications_approved(self, mock_sns: Mock) -> None:
        """Test sending approved notification."""
        mock_sns.publish.return_value = {"MessageId": "test-message-id"}

        result = send_notifications(
            request_id="test-123",
            action="approve",
            requester="test_user",
            approver="admin_user",
            agent_prompt="Test prompt",
            proposed_action="Test action",
            reason="Approved",
        )

        assert result is True
        mock_sns.publish.assert_called_once()
        call_args = mock_sns.publish.call_args
        assert "Approved" in call_args[1]["Subject"]

        # Approved notifications should not have approval links
        message = call_args[1]["Message"]
        assert "APPROVAL ACTIONS:" not in message

    @patch("src.approval_handler.sns")
    @patch("src.approval_handler.SNS_TOPIC_ARN", "test-topic-arn")
    def test_send_notifications_failure(self, mock_sns: Mock) -> None:
        """Test notification sending failure."""
        mock_sns.publish.side_effect = Exception("SNS error")

        result = send_notifications(
            request_id="test-123",
            action="approve",
            requester="test_user",
            approver="admin_user",
            agent_prompt="Test prompt",
            proposed_action="Test action",
            reason="Test reason",
        )

        assert result is False


class TestSlackNotification:
    """Tests for Slack webhook integration."""

    @patch("src.approval_handler.requests.post")
    def test_send_slack_notification_basic(self, mock_post: Mock) -> None:
        from src.approval_handler import send_slack_notification

        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "ok"

        content = {
            "title": "AgentCore HITL Pending Approval",
            "request_id": "req-1",
            "status": "pending",
            "requester": "alice",
            "approver": "",
            "agent_prompt": "Please reset password for bob",
            "proposed_action": "Reset password for bob",
            "reason": "",
            "timestamp": "2025-01-01 00:00:00 UTC",
        }

        with patch.dict(
            "os.environ",
            {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/X/Y"},
        ):
            assert send_slack_notification(content) is True
            mock_post.assert_called_once()

    @patch("src.approval_handler.requests.post")
    def test_send_slack_notification_no_webhook(self, mock_post: Mock) -> None:
        from src.approval_handler import send_slack_notification

        content = {
            "title": "t",
            "request_id": "r",
            "status": "approve",
            "requester": "u",
            "approver": "a",
            "agent_prompt": "p",
            "proposed_action": "pa",
            "reason": "",
        }
        with patch.dict("os.environ", {}, clear=True):
            assert send_slack_notification(content) is False
            mock_post.assert_not_called()

    @patch("src.approval_handler.requests.post")
    def test_send_slack_notification_pending_includes_links(
        self, mock_post: Mock
    ) -> None:
        from src.approval_handler import send_slack_notification

        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "ok"

        content = {
            "title": "AgentCore HITL Pending Approval",
            "request_id": "req-2",
            "status": "pending",
            "requester": "alice",
            "approver": "",
            "agent_prompt": "Action",
            "proposed_action": "Do something",
            "reason": "",
            "timestamp": "2025-01-01 00:00:00 UTC",
        }

        with patch.dict(
            "os.environ",
            {
                "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/X/Y",
                "LAMBDA_FUNCTION_URL": "https://lambda-url",
            },
        ):
            assert send_slack_notification(content)
            args, kwargs = mock_post.call_args
            assert "json" in kwargs
            assert (
                "Approve: https://lambda-url?request_id=req-2&action=approve"
                in kwargs["json"]["text"]
            )
            assert (
                "Reject: https://lambda-url?request_id=req-2&action=reject"
                in kwargs["json"]["text"]
            )
