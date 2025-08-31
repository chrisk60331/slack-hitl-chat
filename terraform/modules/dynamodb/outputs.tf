output "approval_log_table_name" {
  description = "Name of the AgentCore approval log DynamoDB table"
  value       = aws_dynamodb_table.agentcore_approval_log.name
}

output "approval_log_table_arn" {
  description = "ARN of the AgentCore approval log DynamoDB table"
  value       = aws_dynamodb_table.agentcore_approval_log.arn
}

output "state_machine_table_name" {
  description = "Name of the AgentCore state machine DynamoDB table"
  value       = aws_dynamodb_table.agentcore_state_machine.name
}

output "state_machine_table_arn" {
  description = "ARN of the AgentCore state machine DynamoDB table"
  value       = aws_dynamodb_table.agentcore_state_machine.arn
}

output "table_arns" {
  description = "List of all DynamoDB table ARNs"
  value = [
    aws_dynamodb_table.agentcore_approval_log.arn,
    aws_dynamodb_table.agentcore_state_machine.arn,
    aws_dynamodb_table.slack_sessions.arn,
    aws_dynamodb_table.agentcore_config.arn,
    "${aws_dynamodb_table.agentcore_approval_log.arn}/index/*",
    "${aws_dynamodb_table.agentcore_state_machine.arn}/index/*"
  ]
} 

output "slack_sessions_table_name" {
  description = "Name of the Slack sessions DynamoDB table"
  value       = aws_dynamodb_table.slack_sessions.name
}

output "slack_sessions_table_arn" {
  description = "ARN of the Slack sessions DynamoDB table"
  value       = aws_dynamodb_table.slack_sessions.arn
}

output "config_table_name" {
  description = "Name of the AgentCore config DynamoDB table"
  value       = aws_dynamodb_table.agentcore_config.name
}

output "config_table_arn" {
  description = "ARN of the AgentCore config DynamoDB table"
  value       = aws_dynamodb_table.agentcore_config.arn
}