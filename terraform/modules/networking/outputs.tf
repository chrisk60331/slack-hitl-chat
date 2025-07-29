output "vpc_id" {
  description = "ID of the VPC"
  value       = local.vpc_id
}

output "vpc_cidr_block" {
  description = "CIDR block of the VPC"
  value       = var.use_existing_vpc ? data.aws_vpc.existing[0].cidr_block : aws_vpc.vpc[0].cidr_block
}

output "public_subnet_ids" {
  description = "IDs of the public subnets"
  value       = local.public_subnet_ids
}

output "private_subnet_ids" {
  description = "IDs of the private subnets"
  value       = local.private_subnet_ids
}

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