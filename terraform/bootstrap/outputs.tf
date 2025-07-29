output "s3_bucket_name" {
  description = "Name of the S3 bucket for terraform state"
  value       = aws_s3_bucket.terraform_state.bucket
}

output "s3_bucket_arn" {
  description = "ARN of the S3 bucket for terraform state"
  value       = aws_s3_bucket.terraform_state.arn
}

output "dynamodb_table_name" {
  description = "Name of the DynamoDB table for terraform state locking"
  value       = aws_dynamodb_table.terraform_state_lock.name
}

output "dynamodb_table_arn" {
  description = "ARN of the DynamoDB table for terraform state locking"
  value       = aws_dynamodb_table.terraform_state_lock.arn
}

output "backend_config" {
  description = "Backend configuration for use in other terraform configurations"
  value = {
    bucket         = aws_s3_bucket.terraform_state.bucket
    dynamodb_table = aws_dynamodb_table.terraform_state_lock.name
    region         = var.aws_region
  }
} 