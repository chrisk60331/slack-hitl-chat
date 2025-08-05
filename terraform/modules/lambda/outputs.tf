output "lambda_function_name" {
  description = "Name of the Lambda function"
  value       = aws_lambda_function.lambda.function_name
}

output "lambda_function_arn" {
  description = "ARN of the Lambda function"
  value       = aws_lambda_function.lambda.arn
}

output "lambda_function_url" {
  description = "URL of the Lambda function for direct HTTP access"
  value       = var.create_function_url ? aws_lambda_function_url.lambda_url[0].function_url : null
}

output "sns_topic_arn" {
  description = "ARN of the SNS topic"
  value       = var.create_sns_topic ? aws_sns_topic.notifications[0].arn : null
}

output "lambda_log_group_name" {
  description = "Name of the Lambda CloudWatch log group"
  value       = aws_cloudwatch_log_group.lambda_log_group.name
}

output "ecr_repository_url" {
  description = "URL of the ECR repository"
  value       = aws_ecr_repository.lambda.repository_url
} 