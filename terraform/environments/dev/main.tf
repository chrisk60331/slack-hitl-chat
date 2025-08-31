terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
  
  backend "s3" {
    # Backend configuration will be provided via terraform init -backend-config
    # This allows for different environments to use different state keys
  }
}

provider "aws" {
  region = var.aws_region
}

provider "docker" {
  registry_auth {
    address  = data.aws_ecr_authorization_token.token.proxy_endpoint
    username = data.aws_ecr_authorization_token.token.user_name
    password = data.aws_ecr_authorization_token.token.password
  }
}

# ECR authorization for Docker provider
data "aws_ecr_authorization_token" "token" {
  registry_id = data.aws_caller_identity.current.account_id
}

data "aws_caller_identity" "current" {}

locals {
  name_prefix = "agentcore-${var.environment}"
  common_tags = {
    Environment = var.environment
    Project     = "agentcore-marketplace"
    ManagedBy   = "terraform"
  }
}

# Networking Module
module "networking" {
  source = "../../modules/networking"
  
  name_prefix             = local.name_prefix
  vpc_cidr               = var.vpc_cidr
  public_subnet_cidrs    = var.public_subnet_cidrs
  private_subnet_cidrs   = var.private_subnet_cidrs
  use_existing_vpc       = var.use_existing_vpc
  vpc_id                 = var.vpc_id
  private_subnet_ids     = var.private_subnet_ids
  public_subnet_ids      = var.public_subnet_ids
  lambda_security_group_id = var.lambda_security_group_id
  app_security_group_id    = var.app_security_group_id
  alb_security_group_id    = var.alb_security_group_id
  tags                   = local.common_tags
}

# DynamoDB Module
module "dynamodb" {
  source = "../../modules/dynamodb"
  
  name_prefix = local.name_prefix
  tags        = local.common_tags
}

# IAM Module
module "iam" {
  source = "../../modules/iam"
  
  name_prefix                = local.name_prefix
  aws_region                = var.aws_region
  private_subnet_ids        = module.networking.private_subnet_ids
  dynamodb_table_arns       = module.dynamodb.table_arns
  enable_bedrock_guardrails = var.enable_bedrock_guardrails
  bedrock_guardrail_id      = var.bedrock_guardrail_id
  tags                      = local.common_tags
}

# Approval Lambda Module
module "approval_lambda" {
  source = "../../modules/lambda"
  
  name_prefix               = local.name_prefix
  function_name            = "approval"
  source_path              = "${path.module}/../../../"
  docker_target            = "approval"
  handler_file             = "src/approval_handler.py"
  lambda_execution_role_arn = module.iam.lambda_execution_role_arn
  lambda_timeout           = var.lambda_timeout
  lambda_memory_size       = var.lambda_memory_size
  private_subnet_ids       = module.networking.private_subnet_ids
  lambda_security_group_id = module.networking.lambda_security_group_id
  create_function_url      = true
  create_sns_topic         = true
  tags                     = local.common_tags
  
  environment_variables = {
    TABLE_NAME         = module.dynamodb.approval_log_table_name
    SLACK_WEBHOOK_URL  = var.slack_webhook_url
    APPROVAL_LAMBDA_FUNCTION_NAME =  "${local.name_prefix}_approval"
    SLACK_BOT_TOKEN = var.slack_bot_token
    SLACK_CHANNEL_ID = var.slack_channel_id
  }
}

# Execute Lambda Module
module "execute_lambda" {
  source = "../../modules/lambda"
  
  name_prefix                       = local.name_prefix
  function_name                    = "execute"
  source_path                      = "${path.module}/../../../"
  docker_target                    = "execute"
  handler_file                     = "src/execute_handler.py"
  lambda_execution_role_arn        = module.iam.execute_lambda_execution_role_arn
  lambda_timeout                   = 900
  lambda_memory_size               = 10240
  private_subnet_ids               = module.networking.private_subnet_ids
  lambda_security_group_id         = module.networking.lambda_security_group_id
  create_function_url              = false
  create_sns_topic                 = false
  step_functions_state_machine_arn = module.stepfunctions.step_functions_arn
  tags                             = local.common_tags
  
  environment_variables = {
    TABLE_NAME          = module.dynamodb.approval_log_table_name
    GOOGLE_TOKEN_JSON   = var.google_token_json
    MCP_AUTH_TOKEN      = var.mcp_auth_token
    MCP_HOST           = var.mcp_host
    MCP_PORT           = var.mcp_port
    LOG_LEVEL          = "INFO"
    SLACK_WEBHOOK_URL  = var.slack_webhook_url
    APPROVAL_LAMBDA_FUNCTION_NAME =  "${local.name_prefix}_approval"
    SLACK_BOT_TOKEN = var.slack_bot_token
    SLACK_CHANNEL_ID = var.slack_channel_id
  }
}

# Completion Notifier Lambda Module
module "completion_lambda" {
  source = "../../modules/lambda"

  name_prefix               = local.name_prefix
  function_name             = "completion"
  source_path               = "${path.module}/../../../"
  docker_target             = "completion"
  handler_file              = "src/completion_notifier.py"
  lambda_execution_role_arn = module.iam.lambda_execution_role_arn
  lambda_timeout            = 60
  lambda_memory_size        = 256
  private_subnet_ids        = module.networking.private_subnet_ids
  lambda_security_group_id  = module.networking.lambda_security_group_id
  create_function_url       = false
  create_sns_topic          = false
  tags                      = local.common_tags

  environment_variables = {
    TABLE_NAME        = module.dynamodb.approval_log_table_name
    SLACK_BOT_TOKEN   = var.slack_bot_token
    SLACK_CHANNEL_ID  = var.slack_channel_id
  }
}

# Slack Lambda for OAuth and Events
module "slack_lambda" {
  source = "../../modules/lambda"

  name_prefix               = local.name_prefix
  function_name             = "slack"
  source_path               = "${path.module}/../../../"
  docker_target             = "slack"
  handler_file              = "src/slack_lambda.py"
  lambda_execution_role_arn = module.iam.lambda_execution_role_arn
  lambda_timeout            = 600
  lambda_memory_size        = 256
  private_subnet_ids        = module.networking.private_subnet_ids
  lambda_security_group_id  = module.networking.lambda_security_group_id
  create_function_url       = false
  create_sns_topic          = false
  tags                      = local.common_tags

  environment_variables = {
    TABLE_NAME          = module.dynamodb.approval_log_table_name
    SLACK_SESSIONS_TABLE = module.dynamodb.slack_sessions_table_name
    SLACK_SECRETS_NAME   = var.slack_secrets_name != "" ? var.slack_secrets_name : "agentcore-${var.environment}/slack"
    AGENTCORE_GATEWAY_URL = aws_apigatewayv2_api.agentcore_api.api_endpoint
    SLACK_WEBHOOK_URL  = var.slack_webhook_url
    APPROVAL_LAMBDA_FUNCTION_NAME = module.approval_lambda.lambda_function_name
    SLACK_BOT_TOKEN = var.slack_bot_token
    SLACK_CHANNEL_ID = var.slack_channel_id
    STATE_MACHINE_ARN = module.stepfunctions.step_functions_arn
  }
}

# API Lambda (FastAPI with Lambda Web Adapter)
module "api_lambda" {
  source = "../../modules/lambda"

  name_prefix               = local.name_prefix
  function_name             = "api"
  source_path               = "${path.module}/../../../"
  docker_target             = "api"
  handler_file              = "src/api.py"
  lambda_execution_role_arn = module.iam.lambda_execution_role_arn
  lambda_timeout            = 600
  lambda_memory_size        = 1024
  private_subnet_ids        = module.networking.private_subnet_ids
  lambda_security_group_id  = module.networking.lambda_security_group_id
  create_function_url       = false
  create_sns_topic          = false
  tags                      = local.common_tags
  
  environment_variables = {
    TABLE_NAME = module.dynamodb.approval_log_table_name
    CONFIG_TABLE_NAME  = module.dynamodb.config_table_name
    SLACK_WEBHOOK_URL  = var.slack_webhook_url
    APPROVAL_LAMBDA_FUNCTION_NAME = module.approval_lambda.lambda_function_name
    SLACK_BOT_TOKEN = var.slack_bot_token
    SLACK_CHANNEL_ID = var.slack_channel_id
  }
}

resource "aws_apigatewayv2_api" "agentcore_api" {
  name          = "${local.name_prefix}-agentcore-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "api_sessions" {
  api_id                 = aws_apigatewayv2_api.agentcore_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.api_lambda.lambda_function_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "api_messages" {
  api_id                 = aws_apigatewayv2_api.agentcore_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.api_lambda.lambda_function_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "api_stream" {
  api_id                 = aws_apigatewayv2_api.agentcore_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.api_lambda.lambda_function_arn
  integration_method     = "GET"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "api_sns_webhook" {
  api_id                 = aws_apigatewayv2_api.agentcore_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.api_lambda.lambda_function_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "api_sessions" {
  api_id    = aws_apigatewayv2_api.agentcore_api.id
  route_key = "POST /gateway/v1/sessions"
  target    = "integrations/${aws_apigatewayv2_integration.api_sessions.id}"
}

resource "aws_apigatewayv2_route" "api_messages" {
  api_id    = aws_apigatewayv2_api.agentcore_api.id
  route_key = "POST /gateway/v1/sessions/{session_id}/messages"
  target    = "integrations/${aws_apigatewayv2_integration.api_messages.id}"
}

resource "aws_apigatewayv2_route" "api_stream" {
  api_id    = aws_apigatewayv2_api.agentcore_api.id
  route_key = "GET /gateway/v1/sessions/{session_id}/stream"
  target    = "integrations/${aws_apigatewayv2_integration.api_stream.id}"
}

resource "aws_apigatewayv2_route" "api_sns_webhook" {
  api_id    = aws_apigatewayv2_api.agentcore_api.id
  route_key = "POST /webhooks/sns"
  target    = "integrations/${aws_apigatewayv2_integration.api_sns_webhook.id}"
}

resource "aws_lambda_permission" "apigw_invoke_api" {
  statement_id  = "AllowAPIGwInvokeAPI"
  action        = "lambda:InvokeFunction"
  function_name = module.api_lambda.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.agentcore_api.execution_arn}/*/*"
}

resource "aws_apigatewayv2_stage" "agentcore_api" {
  api_id      = aws_apigatewayv2_api.agentcore_api.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_apigatewayv2_api" "slack" {
  name          = "${local.name_prefix}-slack-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "slack_events" {
  api_id                 = aws_apigatewayv2_api.slack.id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.slack_lambda.lambda_function_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "slack_events" {
  api_id    = aws_apigatewayv2_api.slack.id
  route_key = "POST /events"
  target    = "integrations/${aws_apigatewayv2_integration.slack_events.id}"
}

resource "aws_lambda_permission" "apigw_invoke_slack" {
  statement_id  = "AllowAPIGwInvokeSlack"
  action        = "lambda:InvokeFunction"
  function_name = module.slack_lambda.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.slack.execution_arn}/*/*"
}

resource "aws_apigatewayv2_integration" "slack_oauth" {
  api_id                 = aws_apigatewayv2_api.slack.id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.slack_lambda.lambda_function_arn
  integration_method     = "GET"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "slack_oauth" {
  api_id    = aws_apigatewayv2_api.slack.id
  route_key = "GET /oauth/callback"
  target    = "integrations/${aws_apigatewayv2_integration.slack_oauth.id}"
}

resource "aws_apigatewayv2_stage" "slack" {
  api_id      = aws_apigatewayv2_api.slack.id
  name        = "$default"
  auto_deploy = true
}

# Step Functions Module
module "stepfunctions" {
  source = "../../modules/stepfunctions"
  
  name_prefix                        = local.name_prefix
  step_functions_execution_role_arn  = module.iam.step_functions_execution_role_arn
  lambda_function_arn               = module.approval_lambda.lambda_function_arn
  lambda_function_name              = module.approval_lambda.lambda_function_name
  eventbridge_role_arn              = module.iam.eventbridge_role_arn
  stepfunctions_timeout             = var.stepfunctions_timeout
  tags                              = local.common_tags
  execute_lambda_function_arn       = module.execute_lambda.lambda_function_arn
  completion_lambda_function_arn    = module.completion_lambda.lambda_function_arn
} 