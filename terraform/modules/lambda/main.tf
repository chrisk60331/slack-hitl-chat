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
resource "aws_ecr_repository" "agentcore_hitl_approval" {
  name                 = "${var.name_prefix}-hitl-approval"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-hitl-approval"
  })
}

# ECR Repository lifecycle policy
resource "aws_ecr_lifecycle_policy" "agentcore_hitl_approval_policy" {
  repository = aws_ecr_repository.agentcore_hitl_approval.name

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
resource "docker_image" "agentcore_hitl_approval" {
  name = "${aws_ecr_repository.agentcore_hitl_approval.repository_url}:latest"
  
  build {
    context    = var.source_path
    dockerfile = "Dockerfile"
    platform   = "linux/amd64"
    
    # Force rebuild when source files change
    build_args = {
      BUILDKIT_INLINE_CACHE = "1"
    }
  }

  triggers = {
    dockerfile_sha = filesha256("${var.source_path}/Dockerfile")
    pyproject_sha  = filesha256("${var.source_path}/pyproject.toml")
    handler_sha    = filesha256("${var.source_path}/src/approval_handler.py")
    package_sha    = sha256("")
  }
}

# Push image to ECR
resource "docker_registry_image" "agentcore_hitl_approval" {
  name = docker_image.agentcore_hitl_approval.name

  depends_on = [
    aws_ecr_repository.agentcore_hitl_approval,
    docker_image.agentcore_hitl_approval
  ]

  triggers = {
    dockerfile_sha = filesha256("${var.source_path}/Dockerfile")
    pyproject_sha  = filesha256("${var.source_path}/pyproject.toml")
    handler_sha    = filesha256("${var.source_path}/src/approval_handler.py")
    package_sha    = sha256("")
  }
}

# Lambda function using Docker image
resource "aws_lambda_function" "agentcore_hitl_approval" {
  function_name = "${var.name_prefix}_hitl_approval"
  role         = var.lambda_execution_role_arn
  timeout      = var.lambda_timeout
  memory_size  = var.lambda_memory_size
  
  package_type = "Image"
  image_uri    = "${aws_ecr_repository.agentcore_hitl_approval.repository_url}@${docker_registry_image.agentcore_hitl_approval.sha256_digest}"

  # Only configure VPC if private subnets are available
  dynamic "vpc_config" {
    for_each = length(var.private_subnet_ids) > 0 ? [1] : []
    content {
      subnet_ids         = var.private_subnet_ids
      security_group_ids = [var.lambda_security_group_id]
    }
  }

  environment {
    variables = {
      TABLE_NAME         = var.dynamodb_table_name
      SLACK_WEBHOOK_URL  = var.slack_webhook_url
      TEAMS_WEBHOOK_URL  = var.teams_webhook_url
      SNS_TOPIC_ARN      = aws_sns_topic.agentcore_notifications.arn
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda_log_group,
    docker_registry_image.agentcore_hitl_approval,
  ]

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-hitl-approval"
  })
}

# CloudWatch Log Group for Lambda
resource "aws_cloudwatch_log_group" "lambda_log_group" {
  name              = "/aws/lambda/${var.name_prefix}_hitl_approval"
  retention_in_days = 14

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-lambda-logs"
  })
}

# Lambda function URL (optional - for direct HTTP access)
resource "aws_lambda_function_url" "agentcore_hitl_approval_url" {
  function_name      = aws_lambda_function.agentcore_hitl_approval.function_name
  authorization_type = "NONE"

  cors {
    allow_credentials = false
    allow_methods     = ["GET", "POST"]
    allow_origins     = ["*"]
    expose_headers    = ["date", "keep-alive"]
    max_age          = 86400
  }
}

# SNS Topic for notifications
resource "aws_sns_topic" "agentcore_notifications" {
  name = "${var.name_prefix}-notifications"
}

# SNS Topic tags (separate resource)
resource "aws_sns_topic_policy" "agentcore_notifications_policy" {
  arn = aws_sns_topic.agentcore_notifications.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sns:Publish"
        Resource = aws_sns_topic.agentcore_notifications.arn
      }
    ]
  })
}

# Lambda permission for API Gateway (if using API Gateway)
resource "aws_lambda_permission" "api_gateway_lambda" {
  count         = 0  # Set to 1 if using API Gateway
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.agentcore_hitl_approval.function_name
  principal     = "apigateway.amazonaws.com"
} 