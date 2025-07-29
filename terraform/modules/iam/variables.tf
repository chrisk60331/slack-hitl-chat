variable "name_prefix" {
  description = "Prefix for resource naming"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for VPC configuration"
  type        = list(string)
  default     = []
}

variable "dynamodb_table_arns" {
  description = "List of DynamoDB table ARNs for IAM policies"
  type        = list(string)
  default     = []
}

variable "lambda_function_arn" {
  description = "Lambda function ARN for IAM policies"
  type        = string
  default     = ""
}

variable "stepfunctions_arn" {
  description = "Step Functions ARN for IAM policies"
  type        = string
  default     = ""
}

variable "enable_bedrock_guardrails" {
  description = "Enable Bedrock Guardrails policies"
  type        = bool
  default     = false
}

variable "bedrock_guardrail_id" {
  description = "Bedrock Guardrail ID to attach"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
} 