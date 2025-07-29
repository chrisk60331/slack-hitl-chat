output "lambda_function_name" {
  description = "Name of the AgentCore HITL approval Lambda function"
  value       = aws_lambda_function.agentcore_hitl_approval.function_name
}

output "lambda_function_arn" {
  description = "ARN of the AgentCore HITL approval Lambda function"
  value       = aws_lambda_function.agentcore_hitl_approval.arn
}

output "lambda_function_url" {
  description = "URL of the Lambda function for direct HTTP access"
  value       = aws_lambda_function_url.agentcore_hitl_approval_url.function_url
}

output "sns_topic_arn" {
  description = "ARN of the AgentCore notifications SNS topic"
  value       = aws_sns_topic.agentcore_notifications.arn
}

output "lambda_log_group_name" {
  description = "Name of the Lambda CloudWatch log group"
  value       = aws_cloudwatch_log_group.lambda_log_group.name
}

output "ecr_repository_url" {
  description = "URL of the ECR repository"
  value       = aws_ecr_repository.agentcore_hitl_approval.repository_url
} 