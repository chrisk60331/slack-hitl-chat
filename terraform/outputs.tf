# VPC Outputs
output "vpc_id" {
  description = "ID of the VPC"
  value       = local.vpc_id
}

output "vpc_cidr_block" {
  description = "CIDR block of the VPC"
  value       = var.use_existing_vpc ? data.aws_vpc.existing[0].cidr_block : aws_vpc.agentcore_vpc[0].cidr_block
}

output "public_subnet_ids" {
  description = "IDs of the public subnets"
  value       = local.public_subnet_ids
}

output "private_subnet_ids" {
  description = "IDs of the private subnets"
  value       = local.private_subnet_ids
}

# DynamoDB Outputs
output "dynamodb_table_name" {
  description = "Name of the AgentCore approval log DynamoDB table"
  value       = aws_dynamodb_table.agentcore_approval_log.name
}

output "dynamodb_table_arn" {
  description = "ARN of the AgentCore approval log DynamoDB table"
  value       = aws_dynamodb_table.agentcore_approval_log.arn
}

output "dynamodb_state_table_name" {
  description = "Name of the AgentCore state machine DynamoDB table"
  value       = aws_dynamodb_table.agentcore_state_machine.name
}

# Lambda Outputs
output "lambda_function_name" {
  description = "Name of the AgentCore HITL approval Lambda function"
  value       = aws_lambda_function.agentcore_hitl_approval.function_name
}

output "lambda_function_arn" {
  description = "ARN of the AgentCore HITL approval Lambda function"
  value       = aws_lambda_function.agentcore_hitl_approval.arn
}

output "lambda_function_url" {
  description = "Function URL for the Lambda function"
  value       = aws_lambda_function_url.agentcore_hitl_approval_url.function_url
}

# Step Functions Outputs
output "step_functions_arn" {
  description = "ARN of the AgentCore HITL Step Functions state machine"
  value       = aws_sfn_state_machine.agentcore_hitl_workflow.arn
}

output "step_functions_name" {
  description = "Name of the AgentCore HITL Step Functions state machine"
  value       = aws_sfn_state_machine.agentcore_hitl_workflow.name
}

# IAM Outputs
output "lambda_execution_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.lambda_execution_role.arn
}

output "step_functions_execution_role_arn" {
  description = "ARN of the Step Functions execution role"
  value       = aws_iam_role.step_functions_execution_role.arn
}

output "agentcore_app_role_arn" {
  description = "ARN of the AgentCore application role"
  value       = aws_iam_role.agentcore_app_role.arn
}

output "agentcore_instance_profile_name" {
  description = "Name of the AgentCore EC2 instance profile"
  value       = aws_iam_instance_profile.agentcore_instance_profile.name
}

# Security Group Outputs
output "lambda_security_group_id" {
  description = "ID of the Lambda security group"
  value       = local.lambda_security_group_id
}

output "app_security_group_id" {
  description = "ID of the application security group"
  value       = local.app_security_group_id
}

output "alb_security_group_id" {
  description = "ID of the ALB security group"
  value       = local.alb_security_group_id
}

# SNS Outputs
output "sns_topic_arn" {
  description = "ARN of the AgentCore notifications SNS topic"
  value       = aws_sns_topic.agentcore_notifications.arn
}

# EventBridge Outputs
output "eventbridge_rule_name" {
  description = "Name of the EventBridge rule for triggering workflows"
  value       = aws_cloudwatch_event_rule.agentcore_trigger.name
}

# CloudWatch Log Groups
output "lambda_log_group_name" {
  description = "Name of the Lambda CloudWatch log group"
  value       = aws_cloudwatch_log_group.lambda_log_group.name
}

output "step_functions_log_group_name" {
  description = "Name of the Step Functions CloudWatch log group"
  value       = aws_cloudwatch_log_group.step_functions_log_group.name
}

# Environment Variables for Application
output "environment_variables" {
  description = "Environment variables for the AgentCore application"
  value = {
    TABLE_NAME         = aws_dynamodb_table.agentcore_approval_log.name
    AWS_REGION         = var.aws_region
    STEPFUNCTIONS_ARN  = aws_sfn_state_machine.agentcore_hitl_workflow.arn
    SNS_TOPIC_ARN      = aws_sns_topic.agentcore_notifications.arn
  }
}

# Deployment Information
output "deployment_info" {
  description = "Key deployment information"
  value = {
    region                = var.aws_region
    environment          = var.environment
    vpc_id               = local.vpc_id
    lambda_function_url  = aws_lambda_function_url.agentcore_hitl_approval_url.function_url
    step_functions_arn   = aws_sfn_state_machine.agentcore_hitl_workflow.arn
    dynamodb_table       = aws_dynamodb_table.agentcore_approval_log.name
  }
} 