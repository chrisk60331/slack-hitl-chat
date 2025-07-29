variable "name_prefix" {
  description = "Prefix for resource naming"
  type        = string
}

variable "step_functions_execution_role_arn" {
  description = "ARN of the Step Functions execution role"
  type        = string
}

variable "lambda_function_arn" {
  description = "ARN of the Lambda function to invoke"
  type        = string
}

variable "lambda_function_name" {
  description = "Name of the Lambda function"
  type        = string
}

variable "eventbridge_role_arn" {
  description = "ARN of the EventBridge role"
  type        = string
}

variable "stepfunctions_timeout" {
  description = "Step Functions execution timeout in seconds"
  type        = number
  default     = 3600
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
} 