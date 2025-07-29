variable "name_prefix" {
  description = "Prefix for resource naming"
  type        = string
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

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
} 