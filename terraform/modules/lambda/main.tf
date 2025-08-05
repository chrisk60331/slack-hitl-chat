terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = ">= 3.0"
    }
  }
}

# ECR Repository for Lambda Docker images
resource "aws_ecr_repository" "lambda" {
  name                 = "${var.name_prefix}-${var.function_name}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-${var.function_name}"
  })
}

# ECR Repository lifecycle policy
resource "aws_ecr_lifecycle_policy" "lambda_policy" {
  repository = aws_ecr_repository.lambda.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 5 images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v"]
          countType     = "imageCountMoreThan"
          countNumber   = 5
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Delete untagged images older than 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# Build and push Docker image
resource "docker_image" "lambda" {
  name = "${aws_ecr_repository.lambda.repository_url}:latest"
  
  build {
    context    = var.source_path
    dockerfile = "Dockerfile"
    platform   = "linux/amd64"
    target     = var.docker_target
    
    # Force rebuild when source files change
    build_args = {
      BUILDKIT_INLINE_CACHE = "1"
    }
  }

  triggers = {
    dockerfile_sha = filesha256("${var.source_path}/Dockerfile")
    pyproject_sha  = filesha256("${var.source_path}/pyproject.toml")
    handler_sha    = filesha256("${var.source_path}/${var.handler_file}")
    package_sha    = sha256("")
  }
}

# Push image to ECR
resource "docker_registry_image" "lambda" {
  name = docker_image.lambda.name

  depends_on = [
    aws_ecr_repository.lambda,
    docker_image.lambda
  ]

  triggers = {
    dockerfile_sha = filesha256("${var.source_path}/Dockerfile")
    pyproject_sha  = filesha256("${var.source_path}/pyproject.toml")
    handler_sha    = filesha256("${var.source_path}/${var.handler_file}")
    package_sha    = sha256("")
  }
}

# Lambda function using Docker image
resource "aws_lambda_function" "lambda" {
  function_name = "${var.name_prefix}_${var.function_name}"
  role         = var.lambda_execution_role_arn
  timeout      = var.lambda_timeout
  memory_size  = var.lambda_memory_size
  
  package_type = "Image"
  image_uri    = "${aws_ecr_repository.lambda.repository_url}@${docker_registry_image.lambda.sha256_digest}"

  # Only configure VPC if private subnets are available
  dynamic "vpc_config" {
    for_each = length(var.private_subnet_ids) > 0 ? [1] : []
    content {
      subnet_ids         = var.private_subnet_ids
      security_group_ids = [var.lambda_security_group_id]
    }
  }

  environment {
    variables = merge(
      var.environment_variables,
      var.create_sns_topic ? {
        SNS_TOPIC_ARN = aws_sns_topic.notifications[0].arn
      } : {}
    )
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda_log_group,
    docker_registry_image.lambda,
  ]

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-${var.function_name}"
  })
}

# CloudWatch Log Group for Lambda
resource "aws_cloudwatch_log_group" "lambda_log_group" {
  name              = "/aws/lambda/${var.name_prefix}_${var.function_name}"
  retention_in_days = 14

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-${var.function_name}-logs"
  })
}

# Lambda function URL (optional - for direct HTTP access)
resource "aws_lambda_function_url" "lambda_url" {
  count              = var.create_function_url ? 1 : 0
  function_name      = aws_lambda_function.lambda.function_name
  authorization_type = "NONE"

  cors {
    allow_credentials = false
    allow_methods     = ["GET", "POST"]
    allow_origins     = ["*"]
    expose_headers    = ["date", "keep-alive"]
    max_age          = 86400
  }
}

# SNS Topic for notifications (optional)
resource "aws_sns_topic" "notifications" {
  count = var.create_sns_topic ? 1 : 0
  name  = "${var.name_prefix}-${var.function_name}-notifications"

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-${var.function_name}-notifications"
  })
}

# SNS Topic policy (optional)
resource "aws_sns_topic_policy" "notifications_policy" {
  count = var.create_sns_topic ? 1 : 0
  arn   = aws_sns_topic.notifications[0].arn
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sns:Publish"
        Resource = aws_sns_topic.notifications[0].arn
      }
    ]
  })
}

# Lambda permission for Step Functions (optional)
resource "aws_lambda_permission" "step_functions_lambda" {
  count         = var.step_functions_state_machine_arn != "" ? 1 : 0
  statement_id  = "AllowExecutionFromStepFunctions"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.lambda.function_name
  principal     = "states.amazonaws.com"
  source_arn    = var.step_functions_state_machine_arn
} 