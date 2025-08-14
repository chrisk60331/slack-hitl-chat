# Lambda Execution Role
resource "aws_iam_role" "lambda_execution_role" {
  name = "${var.name_prefix}-lambda-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-lambda-execution-role"
  })
}

# Lambda Basic Execution Policy
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Lambda VPC Execution Policy (only attached when Lambda is deployed in VPC)
resource "aws_iam_role_policy_attachment" "lambda_vpc_execution" {
  count      = length(var.private_subnet_ids) > 0 ? 1 : 0
  role       = aws_iam_role.lambda_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_secrets_execution" {
  role       = aws_iam_role.lambda_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/SecretsManagerReadWrite"
}

# ECR Access Policy for Lambda (to pull Docker images)
resource "aws_iam_policy" "lambda_ecr_policy" {
  name        = "${var.name_prefix}-lambda-ecr-policy"
  description = "IAM policy for Lambda to access ECR"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_ecr_policy_attachment" {
  role       = aws_iam_role.lambda_execution_role.name
  policy_arn = aws_iam_policy.lambda_ecr_policy.arn
}

# DynamoDB Access Policy for Lambda
resource "aws_iam_policy" "lambda_dynamodb_policy" {
  name        = "${var.name_prefix}-lambda-dynamodb-policy"
  description = "IAM policy for Lambda to access DynamoDB"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = var.dynamodb_table_arns
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_dynamodb_policy_attachment" {
  role       = aws_iam_role.lambda_execution_role.name
  policy_arn = aws_iam_policy.lambda_dynamodb_policy.arn
}

# Allow API Gateway to invoke Slack Lambda
resource "aws_iam_policy" "apigw_invoke_lambda" {
  name        = "${var.name_prefix}-apigw-invoke-lambda"
  description = "Allow API Gateway to invoke Lambda functions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = "*"
      }
    ]
  })
}

# SNS and SES Policy for Lambda (for notifications)
resource "aws_iam_policy" "lambda_notification_policy" {
  name        = "${var.name_prefix}-lambda-notification-policy"
  description = "IAM policy for Lambda to send notifications"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sns:Publish",
          "ses:SendEmail",
          "ses:SendRawEmail",
          "bedrock:*"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "lambda:GetFunctionUrlConfig"
        ]
        Resource = var.lambda_function_arn != "" ? var.lambda_function_arn : "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_notification_policy_attachment" {
  role       = aws_iam_role.lambda_execution_role.name
  policy_arn = aws_iam_policy.lambda_notification_policy.arn
}

# Step Functions Execution Role
resource "aws_iam_role" "step_functions_execution_role" {
  name = "${var.name_prefix}-step-functions-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "states.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-step-functions-execution-role"
  })
}

# Step Functions Lambda Invoke Policy
resource "aws_iam_policy" "step_functions_lambda_policy" {
  name        = "${var.name_prefix}-step-functions-lambda-policy"
  description = "IAM policy for Step Functions to invoke Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "step_functions_lambda_policy_attachment" {
  role       = aws_iam_role.step_functions_execution_role.name
  policy_arn = aws_iam_policy.step_functions_lambda_policy.arn
}

# Step Functions DynamoDB Policy
resource "aws_iam_policy" "step_functions_dynamodb_policy" {
  name        = "${var.name_prefix}-step-functions-dynamodb-policy"
  description = "IAM policy for Step Functions to access DynamoDB"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = var.dynamodb_table_arns
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "step_functions_dynamodb_policy_attachment" {
  role       = aws_iam_role.step_functions_execution_role.name
  policy_arn = aws_iam_policy.step_functions_dynamodb_policy.arn
}

# Step Functions CloudWatch Logs Policy
resource "aws_iam_policy" "step_functions_logs_policy" {
  name        = "${var.name_prefix}-step-functions-logs-policy"
  description = "IAM policy for Step Functions to write to CloudWatch logs"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "step_functions_logs_policy_attachment" {
  role       = aws_iam_role.step_functions_execution_role.name
  policy_arn = aws_iam_policy.step_functions_logs_policy.arn
}

# AgentCore Application Role (for EC2/ECS/EKS)
resource "aws_iam_role" "agentcore_app_role" {
  name = "${var.name_prefix}-app-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = [
            "ec2.amazonaws.com",
            "ecs-tasks.amazonaws.com"
          ]
        }
      }
    ]
  })

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-app-role"
  })
}

# Bedrock Access Policy for AgentCore App
resource "aws_iam_policy" "agentcore_bedrock_policy" {
  name        = "${var.name_prefix}-bedrock-policy"
  description = "IAM policy for AgentCore to access Bedrock"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:*",
          "bedrock-runtime:*"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "agentcore_bedrock_policy_attachment" {
  role       = aws_iam_role.agentcore_app_role.name
  policy_arn = aws_iam_policy.agentcore_bedrock_policy.arn
}

# DynamoDB Access Policy for AgentCore App
resource "aws_iam_role_policy_attachment" "agentcore_dynamodb_policy_attachment" {
  role       = aws_iam_role.agentcore_app_role.name
  policy_arn = aws_iam_policy.lambda_dynamodb_policy.arn
}

# Step Functions Access Policy for AgentCore App
resource "aws_iam_policy" "agentcore_stepfunctions_policy" {
  name        = "${var.name_prefix}-stepfunctions-policy"
  description = "IAM policy for AgentCore to start Step Functions executions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "states:StartExecution",
          "states:DescribeExecution",
          "states:StopExecution",
          "states:ListExecutions"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "agentcore_stepfunctions_policy_attachment" {
  role       = aws_iam_role.agentcore_app_role.name
  policy_arn = aws_iam_policy.agentcore_stepfunctions_policy.arn
}


resource "aws_iam_role_policy_attachment" "lambda_execution_role" {
  role       = aws_iam_role.lambda_execution_role.name
  policy_arn = aws_iam_policy.agentcore_stepfunctions_policy.arn
}

# Instance Profile for EC2
resource "aws_iam_instance_profile" "agentcore_instance_profile" {
  name = "${var.name_prefix}-instance-profile"
  role = aws_iam_role.agentcore_app_role.name
}

# EventBridge Role for invoking Step Functions
resource "aws_iam_role" "eventbridge_role" {
  name = "${var.name_prefix}-eventbridge-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-eventbridge-role"
  })
}

# IAM Policy for EventBridge to invoke Step Functions
resource "aws_iam_policy" "eventbridge_stepfunctions_policy" {
  name        = "${var.name_prefix}-eventbridge-stepfunctions-policy"
  description = "IAM policy for EventBridge to invoke Step Functions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "states:StartExecution"
        ]
        Resource = var.stepfunctions_arn != "" ? var.stepfunctions_arn : "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "eventbridge_stepfunctions_policy_attachment" {
  role       = aws_iam_role.eventbridge_role.name
  policy_arn = aws_iam_policy.eventbridge_stepfunctions_policy.arn
}

# Optional: Bedrock Guardrails Policies
resource "aws_iam_policy" "bedrock_guardrails_policy" {
  count       = var.enable_bedrock_guardrails ? 1 : 0
  name        = "${var.name_prefix}-bedrock-guardrails-policy"
  description = "IAM policy for Bedrock Guardrails"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:GetGuardrail",
          "bedrock:ApplyGuardrail"
        ]
        Resource = var.bedrock_guardrail_id != "" ? "arn:aws:bedrock:${var.aws_region}:*:guardrail/${var.bedrock_guardrail_id}" : "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "bedrock_guardrails_policy_attachment" {
  count      = var.enable_bedrock_guardrails ? 1 : 0
  role       = aws_iam_role.agentcore_app_role.name
  policy_arn = aws_iam_policy.bedrock_guardrails_policy[0].arn
} 