"""
AWS Lambda function for AgentCore Human-in-the-Loop approval processing.

This function handles approval requests, logs them to DynamoDB, and sends
notifications to Slack or Microsoft Teams.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3
import requests
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field


class ApprovalItem(BaseModel):
    """Pydantic model for approval request items."""
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    requester: str = ""
    approver: str = ""
    agent_prompt: str = ""
    proposed_action: str = ""
    reason: str = ""
    approval_status: str = "pending"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format."""
        return self.model_dump()

    @classmethod
    def from_dynamodb_item(cls, item: Dict[str, Any]) -> 'ApprovalItem':
        """Create from DynamoDB item."""
        return cls(**item)


# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
sns = boto3.client('sns')

# Configuration
TABLE_NAME = os.environ['TABLE_NAME']
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', '')

table = dynamodb.Table(TABLE_NAME)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for processing approval requests.
    
    Args:
        event: Lambda event containing approval request data
        context: Lambda context object
        
    Returns:
        Response dictionary with status and data
    """
    try:
        print(f"Event: {event}")
        if event.get('Input', {}).get('body', {}).get('request_id'):
            request_id = event.get('Input').get('body').get('request_id')
            response = table.get_item(Key={'request_id': request_id})
            item_data = response.get('Item')
            if not item_data:
                raise ValueError(f"Request ID {request_id} not found in approval log.")
            
            approval_item = ApprovalItem.from_dynamodb_item(item_data)
            action = approval_item.approval_status
            event['approval_status'] = approval_item.approval_status
            
            # Prepare response for existing request
            response_data = {
                'request_id': approval_item.request_id,
                'status': action,
                'timestamp': approval_item.timestamp,
                'approval_status': approval_item.approval_status
            }
        else:
            # Create new approval request
            approval_item = ApprovalItem(
                requester=event.get('requester', ''),
                approver=event.get('approver', ''),
                agent_prompt=event.get('agent_prompt', ''),
                proposed_action=event.get('proposed_action', ''),
                reason=event.get('reason', ''),
                approval_status=event.get('approval_status', 'pending')
            )
            
            action = approval_item.approval_status
            
            # Send notifications
            notification_sent = send_notifications(
                request_id=approval_item.request_id,
                action=action,
                requester=approval_item.requester,
                approver=approval_item.approver,
                agent_prompt=approval_item.agent_prompt,
                proposed_action=approval_item.proposed_action,
                reason=approval_item.reason
            )
            
            # Store in DynamoDB
            table.put_item(Item=approval_item.to_dynamodb_item())
            
            # Prepare response
            response_data = {
                'request_id': approval_item.request_id,
                'status': action,
                'timestamp': approval_item.timestamp,
                'notification_sent': notification_sent
            }

        # For HTTP API, return standard HTTP response
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': response_data
        }
        
    except Exception as e:
        error_response = {
            'error': 'operation failed',
            'details': str(e)
        }
        return {
            'statusCode': 500,
            'body': json.dumps(error_response)
        }


def send_notifications(
    request_id: str,
    action: str,
    requester: str,
    approver: str,
    agent_prompt: str,
    proposed_action: str,
    reason: str
) -> bool:
    """
    Send notifications to configured channels.
    
    Args:
        request_id: Unique request identifier
        action: Approval action (approve/reject)
        requester: Who requested the approval
        approver: Who approved/rejected
        agent_prompt: Original agent prompt
        proposed_action: What action was proposed
        reason: Reason for approval/rejection
        
    Returns:
        True if any notification was sent successfully
    """
    notification_sent = False
    
    # Prepare message content
    status_emoji = "✅" if action == "approve" else "❌"
    action_text = "approved" if action == "approve" else "rejected"
    
    message_content = {
        'title': f"AgentCore HITL {action_text.title()}",
        'request_id': request_id,
        'status': f"{status_emoji} {action_text.title()}",
        'requester': requester,
        'approver': approver,
        'agent_prompt': agent_prompt[:500] + "..." if len(agent_prompt) > 500 else agent_prompt,
        'proposed_action': proposed_action[:300] + "..." if len(proposed_action) > 300 else proposed_action,
        'reason': reason,
        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    }
    

    try:
        sns_message = format_sns_message(message_content)
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"AgentCore HITL {message_content['status']}",
            Message=sns_message
        )
        notification_sent = True
        print(f"SNS notification sent for request {request_id}")
    except Exception as e:
        print(f"Error sending SNS notification: {e}")

    return notification_sent


def format_sns_message(content: Dict[str, str]) -> str:
    """Format message for SNS notification."""
    return f"""
AgentCore Human-in-the-Loop {content['status']}

Request ID: {content['request_id']}
Status: {content['status']}
Requester: {content['requester']}
Approver: {content['approver']}
Timestamp: {content['timestamp']}

Agent Prompt:
{content['agent_prompt']}

Proposed Action:
{content['proposed_action']}

Reason:
{content['reason']}
""".strip()


def get_approval_status(request_id: str) -> Optional[ApprovalItem]:
    """
    Retrieve approval status from DynamoDB.
    
    Args:
        request_id: Unique request identifier
        
    Returns:
        ApprovalItem or None if not found
    """
    try:
        response = table.get_item(Key={'request_id': request_id})
        item_data = response.get('Item')
        if item_data:
            return ApprovalItem.from_dynamodb_item(item_data)
        return None
    except ClientError as e:
        print(f"Error retrieving approval status: {e}")
        return None 