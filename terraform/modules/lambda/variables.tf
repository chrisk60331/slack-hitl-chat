variable "name_prefix" {
  description = "Prefix for resource naming"
  type        = string
}

variable "function_name" {
  description = "Name suffix for the Lambda function (e.g., 'approval', 'execute')"
  type        = string
}

variable "source_path" {
  description = "Path to the source code directory"
  type        = string
}

variable "docker_target" {
  description = "Docker build target (e.g., 'approval', 'execute')"
  type        = string
}

variable "handler_file" {
  description = "Handler file path for trigger detection (e.g., 'src/approval_handler.py')"
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

variable "environment_variables" {
  description = "Environment variables for the Lambda function"
  type        = map(string)
  default     = {}
}

variable "create_function_url" {
  description = "Whether to create a Lambda function URL"
  type        = bool
  default     = false
}

variable "create_sns_topic" {
  description = "Whether to create an SNS topic for notifications"
  type        = bool
  default     = false
}

variable "step_functions_state_machine_arn" {
  description = "ARN of the Step Functions state machine (for permissions)"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
} 