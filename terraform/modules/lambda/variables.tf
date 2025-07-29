variable "name_prefix" {
  description = "Prefix for resource naming"
  type        = string
}

variable "source_path" {
  description = "Path to the source code directory"
  type        = string
}

variable "lambda_execution_role_arn" {
  description = "ARN of the Lambda execution role"
  type        = string
}

variable "lambda_timeout" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 30
}

variable "lambda_memory_size" {
  description = "Lambda function memory size in MB"
  type        = number
  default     = 128
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for VPC configuration"
  type        = list(string)
  default     = []
}

variable "lambda_security_group_id" {
  description = "Security group ID for Lambda"
  type        = string
  default     = ""
}

variable "dynamodb_table_name" {
  description = "Name of the DynamoDB table for approval logs"
  type        = string
}

variable "slack_webhook_url" {
  description = "Slack webhook URL for notifications"
  type        = string
  default     = ""
  sensitive   = true
}

variable "teams_webhook_url" {
  description = "Microsoft Teams webhook URL for notifications"
  type        = string
  default     = ""
  sensitive   = true
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
} 