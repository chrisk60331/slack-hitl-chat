# DynamoDB Table for AgentCore Approval Log
resource "aws_dynamodb_table" "agentcore_approval_log" {
  name           = "${var.name_prefix}-approval-log"
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

  tags = merge(var.tags, {
    Name    = "${var.name_prefix}-approval-log"
    Purpose = "Human-in-the-loop approval logging"
  })
}

# DynamoDB Table for Step Functions state tracking
resource "aws_dynamodb_table" "agentcore_state_machine" {
  name           = "${var.name_prefix}-state-machine"
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

  tags = merge(var.tags, {
    Name    = "${var.name_prefix}-state-machine"
    Purpose = "Step Functions execution tracking"
  })
} 

# DynamoDB Table for Slack Sessions mapping (channel:thread -> session_id)
resource "aws_dynamodb_table" "slack_sessions" {
  name         = "${var.name_prefix}-slack-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "thread_key"

  attribute {
    name = "thread_key"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = merge(var.tags, {
    Name    = "${var.name_prefix}-slack-sessions"
    Purpose = "Slack thread to AgentCore session mapping"
  })
}