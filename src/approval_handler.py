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


class ApprovalDecision(BaseModel):
    """Pydantic model for approval decision requests."""
    request_id: str
    action: str = Field(..., pattern="^(approve|reject)$")
    approver: str = ""
    reason: str = ""


if os.getenv('LOCAL_DEV', 'false') == 'true':
    ddb_params = {
        'endpoint_url': 'http://agentcore-dynamodb-local:8000',
        'aws_access_key_id': 'test',
        'aws_secret_access_key': 'test'
    }
else:
    ddb_params = {}

# Initialize AWS clients
dynamodb = boto3.resource(
    'dynamodb',
    region_name=os.environ['AWS_REGION'],
    **ddb_params
)
sns = boto3.client('sns', region_name=os.environ['AWS_REGION'])

# Configuration
TABLE_NAME = os.environ['TABLE_NAME']
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', '')
LAMBDA_FUNCTION_URL = os.environ.get('LAMBDA_FUNCTION_URL', '')

table = dynamodb.Table(TABLE_NAME)


def get_lambda_function_url() -> str:
    """
    Get the Lambda function URL, either from environment or by querying AWS.
    
    Returns:
        The Lambda function URL or empty string if not available
    """
    # First try environment variable
    if LAMBDA_FUNCTION_URL:
        return LAMBDA_FUNCTION_URL
    
    # If not in environment, try to get it dynamically
    try:
        import boto3
        lambda_client = boto3.client('lambda')
        
        # Get function name from the context or environment
        function_name = os.environ.get('AWS_LAMBDA_FUNCTION_NAME', 'agentcore_hitl_approval')
        
        # Get function URL configuration
        response = lambda_client.get_function_url_config(FunctionName=function_name)
        return response.get('FunctionUrl', '')
        
    except Exception as e:
        print(f"Warning: Could not retrieve Lambda function URL: {e}")
        return ''


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for processing approval requests and decisions.
    
    Args:
        event: Lambda event containing request data
        context: Lambda context object
        
    Returns:
        Response dictionary with status and data
    """
    print(f"Approval handler received event: {event}")
    try:
        # Handle approval decision (POST with approval data)
        if _is_approval_decision(event):
            return _handle_approval_decision(event)
        
        # Handle status check (existing request ID lookup)
        elif _has_request_id_for_status_check(event):
            return _handle_status_check(event)
        
        # Handle new approval request creation
        else:
            return _handle_new_approval_request(event)
            
    except Exception as e:
        error_response = {
            'error': 'operation failed',
            'details': str(e)
        }
        return {
            'statusCode': 500,
            'body': json.dumps(error_response)
        }


def _is_approval_decision(event: Dict[str, Any]) -> bool:
    """Check if the event represents an approval decision."""
    # Check for direct approval decision in body
    body = event.get('body')
    if isinstance(body, str):
        try:
            parsed_body = json.loads(body)
            return 'action' in parsed_body and 'request_id' in parsed_body
        except (json.JSONDecodeError, TypeError):
            pass
    elif isinstance(body, dict):
        return 'action' in body and 'request_id' in body
    
    # Check for query parameters (for GET requests with approval)
    query_params = event.get('queryStringParameters') or {}
    return 'action' in query_params and 'request_id' in query_params


def _has_request_id_for_status_check(event: Dict[str, Any]) -> bool:
    """Check if the event has a request_id for status checking."""
    # Check various possible locations for request_id in Step Functions input
    # Direct access to request_id
    if event.get('request_id'):
        return True
    
    # Step Functions Input format
    if event.get('Input', {}).get('body', {}).get('request_id'):
        return True
    
    # Direct body access
    if event.get('body', {}).get('request_id'):
        return True
    
    # Query parameters
    if event.get('queryStringParameters', {}).get('request_id'):
        return True
    
    return False


def _extract_request_id_for_status_check(event: Dict[str, Any]) -> str:
    """Extract request_id from various possible event structures."""
    # Try direct access first
    if event.get('request_id'):
        return event['request_id']
    
    # Step Functions Input format
    if event.get('Input', {}).get('body', {}).get('request_id'):
        return event['Input']['body']['request_id']
    
    # Direct body access
    if event.get('body', {}).get('request_id'):
        return event['body']['request_id']
    
    # Query parameters
    if event.get('queryStringParameters', {}).get('request_id'):
        return event['queryStringParameters']['request_id']
    
    raise ValueError("No request_id found in event for status check")


def _handle_approval_decision(event: Dict[str, Any]) -> Dict[str, Any]:
    """Handle approval decision requests."""
    # Extract decision data from event
    decision_data = _extract_decision_data(event)
    decision = ApprovalDecision(**decision_data)
    
    # Get existing approval item
    response = table.get_item(Key={'request_id': decision.request_id})
    item_data = response.get('Item')
    if not item_data:
        raise ValueError(f"Request ID {decision.request_id} not found in approval log.")
    
    approval_item = ApprovalItem.from_dynamodb_item(item_data)
    
    # Update approval status
    approval_item.approval_status = decision.action
    approval_item.approver = decision.approver
    if decision.reason:
        approval_item.reason = decision.reason
    
    # Update timestamp for the decision
    approval_item.timestamp = datetime.now(timezone.utc).isoformat()
    
    # Save updated item to DynamoDB
    table.put_item(Item=approval_item.to_dynamodb_item())
    
    # Send notification about the decision
    send_notifications(
        request_id=approval_item.request_id,
        action=approval_item.approval_status,
        requester=approval_item.requester,
        approver=approval_item.approver,
        agent_prompt=approval_item.agent_prompt,
        proposed_action=approval_item.proposed_action,
        reason=approval_item.reason
    )
    
    response_data = {
        'request_id': approval_item.request_id,
        'status': approval_item.approval_status,
        'approver': approval_item.approver,
        'timestamp': approval_item.timestamp,
        'message': f"Request {decision.action} successfully"
    }
    
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': response_data
    }


def _extract_decision_data(event: Dict[str, Any]) -> Dict[str, Any]:
    """Extract decision data from various event formats."""
    # Try body first (POST requests)
    body = event.get('body')
    if isinstance(body, str):
        try:
            return json.loads(body)
        except (json.JSONDecodeError, TypeError):
            pass
    elif isinstance(body, dict):
        return body
    
    # Try query parameters (GET requests)
    query_params = event.get('queryStringParameters') or {}
    if 'action' in query_params and 'request_id' in query_params:
        return {
            'request_id': query_params['request_id'],
            'action': query_params['action'],
            'approver': query_params.get('approver', ''),
            'reason': query_params.get('reason', '')
        }
    
    raise ValueError("No valid decision data found in request")


def _handle_status_check(event: Dict[str, Any]) -> Dict[str, Any]:
    """Handle existing status check requests."""
    request_id = _extract_request_id_for_status_check(event)
    response = table.get_item(Key={'request_id': request_id})
    item_data = response.get('Item')
    if not item_data:
        raise ValueError(f"Approval request {request_id} not found")
    
    approval_item = ApprovalItem.from_dynamodb_item(item_data)
    
    response_data = {
        'request_id': approval_item.request_id,
        'status': approval_item.approval_status,
        'timestamp': approval_item.timestamp,
        'approval_status': approval_item.approval_status
    }
    
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': response_data
    }


def _handle_new_approval_request(event: Dict[str, Any]) -> Dict[str, Any]:
    """Handle new approval request creation."""
    # Create new approval request
    if 'Input' in event:
        event = event['Input']

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
        'notification_sent': notification_sent,
        'proposed_action': approval_item.proposed_action
    }
    
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': response_data
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
        action: Approval action (approve/reject/pending)
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
    if action == "pending":
        status_emoji = "⏳"
        action_text = "Pending Approval"
        status = "pending"
    elif action == "approve":
        status_emoji = "✅"
        action_text = "Approved"
        status = "✅ Approved"
    else:  # reject
        status_emoji = "❌"
        action_text = "Rejected"
        status = "❌ Rejected"
    
    message_content = {
        'title': f"AgentCore HITL {action_text}",
        'request_id': request_id,
        'status': status,
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
    base_message = f"""
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
{content['reason']}"""

    # Add approval links only for pending requests
    function_url = get_lambda_function_url()
    if content.get('status') == 'pending' and function_url:
        approval_link = f"{function_url}?request_id={content['request_id']}&action=approve&approver=admin"
        rejection_link = f"{function_url}?request_id={content['request_id']}&action=reject&approver=admin"
        
        base_message += f"""

🔗 APPROVAL ACTIONS:
✅ Approve: {approval_link}
❌ Reject: {rejection_link}

Note: Click the links above to approve or reject this request."""

    return base_message.strip()


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


def read_sns_messages_locally(region_name: str = 'us-east-1', max_messages: int = 10) -> list[Dict[str, Any]]:
    """
    Read SNS messages locally for testing and debugging.
    
    Note: This requires the SNS topic to have an SQS subscription for local testing.
    In production, use CloudWatch logs or other monitoring tools.
    
    Args:
        region_name: AWS region name
        max_messages: Maximum number of messages to retrieve
        
    Returns:
        List of message dictionaries
    """
    try:
        import boto3
        from botocore.exceptions import NoCredentialsError, PartialCredentialsError
        
        # Check if we have AWS credentials
        try:
            session = boto3.Session()
            credentials = session.get_credentials()
            if not credentials:
                print("Warning: No AWS credentials found. Cannot read SNS messages.")
                return []
        except (NoCredentialsError, PartialCredentialsError):
            print("Warning: AWS credentials not configured properly.")
            return []
        
        # For local testing, we would typically need an SQS queue subscribed to the SNS topic
        # This is a placeholder implementation that would need actual SQS integration
        print(f"Reading SNS messages from region: {region_name}")
        print(f"SNS Topic ARN: {SNS_TOPIC_ARN}")
        print("Note: For local testing, subscribe an SQS queue to the SNS topic and read from SQS.")
        
        # TODO: Implement actual SQS message reading
        # sqs = boto3.client('sqs', region_name=region_name)
        # queue_url = "your-test-queue-url"  # Would need to be configured
        # response = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=max_messages)
        # messages = response.get('Messages', [])
        
        return []
        
    except Exception as e:
        print(f"Error reading SNS messages: {e}")
        return []


def create_test_sqs_queue_for_sns(queue_name: str = "agentcore-sns-test-queue", region_name: str = 'us-east-1') -> Optional[str]:
    """
    Create a test SQS queue and subscribe it to the SNS topic for local testing.
    
    Args:
        queue_name: Name for the SQS queue
        region_name: AWS region name
        
    Returns:
        Queue URL if successful, None otherwise
    """
    try:
        import boto3
        
        sqs = boto3.client('sqs', region_name=region_name)
        sns = boto3.client('sns', region_name=region_name)
        
        # Create SQS queue
        queue_response = sqs.create_queue(
            QueueName=queue_name,
            Attributes={
                'MessageRetentionPeriod': '1209600',  # 14 days
                'VisibilityTimeoutSeconds': '30'
            }
        )
        queue_url = queue_response['QueueUrl']
        
        # Get queue attributes to get the ARN
        queue_attrs = sqs.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=['QueueArn']
        )
        queue_arn = queue_attrs['Attributes']['QueueArn']
        
        # Subscribe queue to SNS topic
        if SNS_TOPIC_ARN:
            sns.subscribe(
                TopicArn=SNS_TOPIC_ARN,
                Protocol='sqs',
                Endpoint=queue_arn
            )
            print(f"Successfully created test queue: {queue_url}")
            print(f"Subscribed to SNS topic: {SNS_TOPIC_ARN}")
            return queue_url
        else:
            print("Warning: SNS_TOPIC_ARN not configured")
            return queue_url
            
    except Exception as e:
        print(f"Error creating test SQS queue: {e}")
        return None


def read_messages_from_test_queue(queue_url: str, max_messages: int = 10, region_name: str = 'us-east-1') -> list[Dict[str, Any]]:
    """
    Read messages from the test SQS queue to see SNS notifications.
    
    Args:
        queue_url: SQS queue URL
        max_messages: Maximum number of messages to retrieve
        region_name: AWS region name
        
    Returns:
        List of parsed message dictionaries
    """
    try:
        import boto3
        
        sqs = boto3.client('sqs', region_name=region_name)
        
        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=5,
            AttributeNames=['All']
        )
        
        messages = response.get('Messages', [])
        parsed_messages = []
        
        for message in messages:
            try:
                # Parse SNS message body
                body = json.loads(message['Body'])
                sns_message = json.loads(body['Message']) if isinstance(body.get('Message'), str) else body.get('Message', body)
                
                parsed_message = {
                    'message_id': message.get('MessageId'),
                    'receipt_handle': message.get('ReceiptHandle'),
                    'sns_subject': body.get('Subject', ''),
                    'sns_message': body.get('Message', ''),
                    'parsed_content': sns_message if isinstance(sns_message, dict) else {},
                    'timestamp': body.get('Timestamp', ''),
                    'raw_body': message['Body']
                }
                parsed_messages.append(parsed_message)
                
                # Delete message after reading (optional)
                # sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message['ReceiptHandle'])
                
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Error parsing message: {e}")
                continue
        
        return parsed_messages
        
    except Exception as e:
        print(f"Error reading messages from queue: {e}")
        return [] 