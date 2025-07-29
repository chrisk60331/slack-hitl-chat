variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (e.g., dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets"
  type        = list(string)
  default     = ["10.0.3.0/24", "10.0.4.0/24"]
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

variable "stepfunctions_timeout" {
  description = "Step Functions execution timeout in seconds"
  type        = number
  default     = 3600
}

variable "bedrock_agent_id" {
  description = "Bedrock Agent ID for the deployed AgentCore application"
  type        = string
  default     = ""
}

variable "bedrock_agent_alias_id" {
  description = "Bedrock Agent Alias ID for the deployed AgentCore application"
  type        = string
  default     = "TSTALIASID"
}

# VPC Configuration Variables
variable "use_existing_vpc" {
  description = "Whether to use existing VPC resources instead of creating new ones"
  type        = bool
  default     = false
}

variable "vpc_id" {
  description = "ID of existing VPC to use"
  type        = string
  default     = ""
}

variable "private_subnet_ids" {
  description = "List of existing private subnet IDs"
  type        = list(string)
  default     = []
}

variable "public_subnet_ids" {
  description = "List of existing public subnet IDs"
  type        = list(string)
  default     = []
}

variable "lambda_security_group_id" {
  description = "ID of existing security group for Lambda functions"
  type        = string
  default     = ""
}

variable "app_security_group_id" {
  description = "ID of existing security group for applications"
  type        = string
  default     = ""
}

variable "alb_security_group_id" {
  description = "ID of existing security group for ALB"
  type        = string
  default     = ""
} 