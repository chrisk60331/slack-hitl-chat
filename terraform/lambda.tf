# ECR Repository for Lambda Docker images
resource "aws_ecr_repository" "agentcore_hitl_approval" {
  name                 = "agentcore-hitl-approval"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name        = "agentcore-hitl-approval"
    Environment = var.environment
  }
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
    context    = "${path.module}/.."
    dockerfile = "Dockerfile"
    platform   = "linux/amd64"
    
    # Force rebuild when source files change
    build_args = {
      BUILDKIT_INLINE_CACHE = "1"
    }
  }

  triggers = {
    dockerfile_sha = filesha256("${path.module}/../Dockerfile")
    pyproject_sha  = filesha256("${path.module}/../pyproject.toml")
    handler_sha    = filesha256("${path.module}/../src/approval_handler.py")
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
    dockerfile_sha = filesha256("${path.module}/../Dockerfile")
    pyproject_sha  = filesha256("${path.module}/../pyproject.toml")
    handler_sha    = filesha256("${path.module}/../src/approval_handler.py")
    package_sha    = sha256("")
  }
}

# Lambda function using Docker image
resource "aws_lambda_function" "agentcore_hitl_approval" {
  function_name = "agentcore_hitl_approval"
  role         = aws_iam_role.lambda_execution_role.arn
  timeout      = var.lambda_timeout
  memory_size  = var.lambda_memory_size
  
  package_type = "Image"
  image_uri    = "${aws_ecr_repository.agentcore_hitl_approval.repository_url}@${docker_registry_image.agentcore_hitl_approval.sha256_digest}"

  # Only configure VPC if private subnets are available
  dynamic "vpc_config" {
    for_each = length(local.private_subnet_ids) > 0 ? [1] : []
    content {
      subnet_ids         = local.private_subnet_ids
      security_group_ids = [local.lambda_security_group_id]
    }
  }

  environment {
    variables = {
      TABLE_NAME         = aws_dynamodb_table.agentcore_approval_log.name
      SLACK_WEBHOOK_URL  = var.slack_webhook_url
      TEAMS_WEBHOOK_URL  = var.teams_webhook_url
      SNS_TOPIC_ARN      = aws_sns_topic.agentcore_notifications.arn
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic_execution,
    aws_iam_role_policy_attachment.lambda_dynamodb_policy_attachment,
    aws_cloudwatch_log_group.lambda_log_group,
    docker_registry_image.agentcore_hitl_approval,
  ]

  tags = {
    Name        = "agentcore-hitl-approval"
    Environment = var.environment
  }
}

# CloudWatch Log Group for Lambda
resource "aws_cloudwatch_log_group" "lambda_log_group" {
  name              = "/aws/lambda/agentcore_hitl_approval"
  retention_in_days = 14

  tags = {
    Name        = "agentcore-lambda-logs"
    Environment = var.environment
  }
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
  name = "agentcore-notifications"
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

# Lambda permission for Step Functions
resource "aws_lambda_permission" "step_functions_lambda" {
  statement_id  = "AllowExecutionFromStepFunctions"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.agentcore_hitl_approval.function_name
  principal     = "states.amazonaws.com"
  source_arn    = aws_sfn_state_machine.agentcore_hitl_workflow.arn
} 