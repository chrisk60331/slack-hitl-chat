output "lambda_execution_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.lambda_execution_role.arn
}

output "lambda_execution_role_name" {
  description = "Name of the Lambda execution role"
  value       = aws_iam_role.lambda_execution_role.name
}

output "step_functions_execution_role_arn" {
  description = "ARN of the Step Functions execution role"
  value       = aws_iam_role.step_functions_execution_role.arn
}

output "step_functions_execution_role_name" {
  description = "Name of the Step Functions execution role"
  value       = aws_iam_role.step_functions_execution_role.name
}

output "agentcore_app_role_arn" {
  description = "ARN of the AgentCore application role"
  value       = aws_iam_role.agentcore_app_role.arn
}

output "agentcore_app_role_name" {
  description = "Name of the AgentCore application role"
  value       = aws_iam_role.agentcore_app_role.name
}

output "agentcore_instance_profile_name" {
  description = "Name of the AgentCore EC2 instance profile"
  value       = aws_iam_instance_profile.agentcore_instance_profile.name
}

output "eventbridge_role_arn" {
  description = "ARN of the EventBridge role"
  value       = aws_iam_role.eventbridge_role.arn
}

output "eventbridge_role_name" {
  description = "Name of the EventBridge role"
  value       = aws_iam_role.eventbridge_role.name
} 