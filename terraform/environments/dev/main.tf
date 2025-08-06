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
  lambda_function_arn       = "" # Will be populated after lambda module
  stepfunctions_arn         = "" # Will be populated after stepfunctions module
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
    TEAMS_WEBHOOK_URL  = var.teams_webhook_url
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
  lambda_timeout                   = var.execute_lambda_timeout
  lambda_memory_size               = var.execute_lambda_memory_size
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
    OPENAI_API_KEY     = var.openai_api_key
    LOG_LEVEL          = "INFO"
  }
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
} 