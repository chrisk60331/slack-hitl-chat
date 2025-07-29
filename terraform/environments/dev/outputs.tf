# VPC Outputs
output "vpc_id" {
  description = "ID of the VPC"
  value       = module.networking.vpc_id
}

output "vpc_cidr_block" {
  description = "CIDR block of the VPC"
  value       = module.networking.vpc_cidr_block
}

output "public_subnet_ids" {
  description = "IDs of the public subnets"
  value       = module.networking.public_subnet_ids
}

output "private_subnet_ids" {
  description = "IDs of the private subnets"
  value       = module.networking.private_subnet_ids
}

# DynamoDB Outputs
output "dynamodb_table_name" {
  description = "Name of the AgentCore approval log DynamoDB table"
  value       = module.dynamodb.approval_log_table_name
}

output "dynamodb_table_arn" {
  description = "ARN of the AgentCore approval log DynamoDB table"
  value       = module.dynamodb.approval_log_table_arn
}

output "dynamodb_state_table_name" {
  description = "Name of the AgentCore state machine DynamoDB table"
  value       = module.dynamodb.state_machine_table_name
}

# Lambda Outputs
output "lambda_function_name" {
  description = "Name of the AgentCore HITL approval Lambda function"
  value       = module.lambda.lambda_function_name
}

output "lambda_function_arn" {
  description = "ARN of the AgentCore HITL approval Lambda function"
  value       = module.lambda.lambda_function_arn
}

output "lambda_function_url" {
  description = "URL of the Lambda function for direct HTTP access"
  value       = module.lambda.lambda_function_url
}

# Step Functions Outputs
output "step_functions_arn" {
  description = "ARN of the AgentCore HITL Step Functions state machine"
  value       = module.stepfunctions.step_functions_arn
}

output "step_functions_name" {
  description = "Name of the AgentCore HITL Step Functions state machine"
  value       = module.stepfunctions.step_functions_name
}

# IAM Outputs
output "lambda_execution_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = module.iam.lambda_execution_role_arn
}

output "step_functions_execution_role_arn" {
  description = "ARN of the Step Functions execution role"
  value       = module.iam.step_functions_execution_role_arn
}

output "agentcore_app_role_arn" {
  description = "ARN of the AgentCore application role"
  value       = module.iam.agentcore_app_role_arn
}

output "agentcore_instance_profile_name" {
  description = "Name of the AgentCore EC2 instance profile"
  value       = module.iam.agentcore_instance_profile_name
}

# Security Group Outputs
output "lambda_security_group_id" {
  description = "ID of the Lambda security group"
  value       = module.networking.lambda_security_group_id
}

output "app_security_group_id" {
  description = "ID of the application security group"
  value       = module.networking.app_security_group_id
}

output "alb_security_group_id" {
  description = "ID of the ALB security group"
  value       = module.networking.alb_security_group_id
}

# SNS Outputs
output "sns_topic_arn" {
  description = "ARN of the AgentCore notifications SNS topic"
  value       = module.lambda.sns_topic_arn
}

# EventBridge Outputs
output "eventbridge_rule_name" {
  description = "Name of the EventBridge rule for triggering workflows"
  value       = module.stepfunctions.eventbridge_rule_name
}

# CloudWatch Log Groups
output "lambda_log_group_name" {
  description = "Name of the Lambda CloudWatch log group"
  value       = module.lambda.lambda_log_group_name
}

output "step_functions_log_group_name" {
  description = "Name of the Step Functions CloudWatch log group"
  value       = module.stepfunctions.step_functions_log_group_name
}

# Environment Variables for Application
output "environment_variables" {
  description = "Environment variables for the AgentCore application"
  value = {
    TABLE_NAME         = module.dynamodb.approval_log_table_name
    AWS_REGION         = var.aws_region
    STEPFUNCTIONS_ARN  = module.stepfunctions.step_functions_arn
    SNS_TOPIC_ARN      = module.lambda.sns_topic_arn
  }
}

# Deployment Information
output "deployment_info" {
  description = "Key deployment information"
  value = {
    region                = var.aws_region
    environment          = var.environment
    vpc_id               = module.networking.vpc_id
    lambda_function_url  = module.lambda.lambda_function_url
    step_functions_arn   = module.stepfunctions.step_functions_arn
    dynamodb_table       = module.dynamodb.approval_log_table_name
  }
} 