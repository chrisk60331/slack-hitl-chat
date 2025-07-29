# DynamoDB Table for AgentCore Approval Log
resource "aws_dynamodb_table" "agentcore_approval_log" {
  name           = "agentcore-approval-log"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "request_id"

  attribute {
    name = "request_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  # Global Secondary Index for querying by status
  global_secondary_index {
    name               = "StatusIndex"
    hash_key           = "status"
    range_key          = "timestamp"
    projection_type    = "ALL"
  }

  # Global Secondary Index for querying by timestamp
  global_secondary_index {
    name               = "TimestampIndex"
    hash_key           = "timestamp"
    projection_type    = "ALL"
  }

  # Point-in-time recovery
  point_in_time_recovery {
    enabled = true
  }

  # Server-side encryption
  server_side_encryption {
    enabled = true
  }

  tags = {
    Name        = "agentcore-approval-log"
    Environment = var.environment
    Purpose     = "Human-in-the-loop approval logging"
  }
}

# DynamoDB Table for Step Functions state tracking
resource "aws_dynamodb_table" "agentcore_state_machine" {
  name           = "agentcore-state-machine"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "execution_arn"

  attribute {
    name = "execution_arn"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  # Global Secondary Index for querying by creation time
  global_secondary_index {
    name               = "CreatedAtIndex"
    hash_key           = "created_at"
    projection_type    = "ALL"
  }

  # TTL for automatic cleanup of old executions
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  # Point-in-time recovery
  point_in_time_recovery {
    enabled = true
  }

  # Server-side encryption
  server_side_encryption {
    enabled = true
  }

  tags = {
    Name        = "agentcore-state-machine"
    Environment = var.environment
    Purpose     = "Step Functions execution tracking"
  }
} 