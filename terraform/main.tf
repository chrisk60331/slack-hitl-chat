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

# Data sources for existing VPC resources
data "aws_vpc" "existing" {
  count = var.use_existing_vpc ? 1 : 0
  id    = var.vpc_id
}

data "aws_subnets" "existing_private" {
  count = var.use_existing_vpc && length(var.private_subnet_ids) > 0 ? 1 : 0
  filter {
    name   = "subnet-id"
    values = var.private_subnet_ids
  }
}

data "aws_subnets" "existing_public" {
  count = var.use_existing_vpc && length(var.public_subnet_ids) > 0 ? 1 : 0
  filter {
    name   = "subnet-id"
    values = var.public_subnet_ids
  }
}

data "aws_security_group" "existing_lambda" {
  count = var.use_existing_vpc && var.lambda_security_group_id != "" ? 1 : 0
  id    = var.lambda_security_group_id
}

data "aws_security_group" "existing_app" {
  count = var.use_existing_vpc && var.app_security_group_id != "" ? 1 : 0
  id    = var.app_security_group_id
}

data "aws_security_group" "existing_alb" {
  count = var.use_existing_vpc && var.alb_security_group_id != "" ? 1 : 0
  id    = var.alb_security_group_id
}

# VPC Configuration (only created if not using existing)
resource "aws_vpc" "agentcore_vpc" {
  count                = var.use_existing_vpc ? 0 : 1
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name        = "agentcore-vpc"
    Environment = var.environment
  }
}

# Local values to simplify resource references
locals {
  vpc_id = var.use_existing_vpc ? var.vpc_id : aws_vpc.agentcore_vpc[0].id
  private_subnet_ids = var.use_existing_vpc ? var.private_subnet_ids : [aws_subnet.private_subnet_1[0].id, aws_subnet.private_subnet_2[0].id]
  public_subnet_ids = var.use_existing_vpc ? var.public_subnet_ids : [aws_subnet.public_subnet_1[0].id, aws_subnet.public_subnet_2[0].id]
  lambda_security_group_id = var.use_existing_vpc && var.lambda_security_group_id != "" ? var.lambda_security_group_id : aws_security_group.agentcore_lambda_sg[0].id
  app_security_group_id = var.use_existing_vpc && var.app_security_group_id != "" ? var.app_security_group_id : aws_security_group.agentcore_app_sg[0].id
  alb_security_group_id = var.use_existing_vpc && var.alb_security_group_id != "" ? var.alb_security_group_id : aws_security_group.agentcore_alb_sg[0].id
}

# Internet Gateway (only created if not using existing)
resource "aws_internet_gateway" "agentcore_igw" {
  count  = var.use_existing_vpc ? 0 : 1
  vpc_id = local.vpc_id

  tags = {
    Name        = "agentcore-igw"
    Environment = var.environment
  }
}

# Public Subnets (only created if not using existing)
resource "aws_subnet" "public_subnet_1" {
  count                   = var.use_existing_vpc ? 0 : 1
  vpc_id                  = local.vpc_id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = {
    Name        = "agentcore-public-subnet-1"
    Environment = var.environment
    Type        = "public"
  }
}

resource "aws_subnet" "public_subnet_2" {
  count                   = var.use_existing_vpc ? 0 : 1
  vpc_id                  = local.vpc_id
  cidr_block              = "10.0.2.0/24"
  availability_zone       = data.aws_availability_zones.available.names[1]
  map_public_ip_on_launch = true

  tags = {
    Name        = "agentcore-public-subnet-2"
    Environment = var.environment
    Type        = "public"
  }
}

# Private Subnets (only created if not using existing)
resource "aws_subnet" "private_subnet_1" {
  count             = var.use_existing_vpc ? 0 : 1
  vpc_id            = local.vpc_id
  cidr_block        = "10.0.3.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]

  tags = {
    Name        = "agentcore-private-subnet-1"
    Environment = var.environment
    Type        = "private"
  }
}

resource "aws_subnet" "private_subnet_2" {
  count             = var.use_existing_vpc ? 0 : 1
  vpc_id            = local.vpc_id
  cidr_block        = "10.0.4.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]

  tags = {
    Name        = "agentcore-private-subnet-2"
    Environment = var.environment
    Type        = "private"
  }
}

# NAT Gateways (only created if not using existing)
resource "aws_eip" "nat_eip_1" {
  count  = var.use_existing_vpc ? 0 : 1
  domain = "vpc"
  depends_on = [aws_internet_gateway.agentcore_igw]

  tags = {
    Name        = "agentcore-nat-eip-1"
    Environment = var.environment
  }
}

resource "aws_eip" "nat_eip_2" {
  count  = var.use_existing_vpc ? 0 : 1
  domain = "vpc"
  depends_on = [aws_internet_gateway.agentcore_igw]

  tags = {
    Name        = "agentcore-nat-eip-2"
    Environment = var.environment
  }
}

resource "aws_nat_gateway" "nat_gateway_1" {
  count         = var.use_existing_vpc ? 0 : 1
  allocation_id = aws_eip.nat_eip_1[0].id
  subnet_id     = aws_subnet.public_subnet_1[0].id

  tags = {
    Name        = "agentcore-nat-gateway-1"
    Environment = var.environment
  }
}

resource "aws_nat_gateway" "nat_gateway_2" {
  count         = var.use_existing_vpc ? 0 : 1
  allocation_id = aws_eip.nat_eip_2[0].id
  subnet_id     = aws_subnet.public_subnet_2[0].id

  tags = {
    Name        = "agentcore-nat-gateway-2"
    Environment = var.environment
  }
}

# Route Tables (only created if not using existing)
resource "aws_route_table" "public_rt" {
  count  = var.use_existing_vpc ? 0 : 1
  vpc_id = local.vpc_id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.agentcore_igw[0].id
  }

  tags = {
    Name        = "agentcore-public-route-table"
    Environment = var.environment
  }
}

resource "aws_route_table" "private_rt_1" {
  count  = var.use_existing_vpc ? 0 : 1
  vpc_id = local.vpc_id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.nat_gateway_1[0].id
  }

  tags = {
    Name        = "agentcore-private-route-table-1"
    Environment = var.environment
  }
}

resource "aws_route_table" "private_rt_2" {
  count  = var.use_existing_vpc ? 0 : 1
  vpc_id = local.vpc_id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.nat_gateway_2[0].id
  }

  tags = {
    Name        = "agentcore-private-route-table-2"
    Environment = var.environment
  }
}

# Route Table Associations (only created if not using existing)
resource "aws_route_table_association" "public_subnet_1_association" {
  count          = var.use_existing_vpc ? 0 : 1
  subnet_id      = aws_subnet.public_subnet_1[0].id
  route_table_id = aws_route_table.public_rt[0].id
}

resource "aws_route_table_association" "public_subnet_2_association" {
  count          = var.use_existing_vpc ? 0 : 1
  subnet_id      = aws_subnet.public_subnet_2[0].id
  route_table_id = aws_route_table.public_rt[0].id
}

resource "aws_route_table_association" "private_subnet_1_association" {
  count          = var.use_existing_vpc ? 0 : 1
  subnet_id      = aws_subnet.private_subnet_1[0].id
  route_table_id = aws_route_table.private_rt_1[0].id
}

resource "aws_route_table_association" "private_subnet_2_association" {
  count          = var.use_existing_vpc ? 0 : 1
  subnet_id      = aws_subnet.private_subnet_2[0].id
  route_table_id = aws_route_table.private_rt_2[0].id
}

# Security Groups (only created if not using existing)
resource "aws_security_group" "agentcore_lambda_sg" {
  count       = var.use_existing_vpc ? 0 : 1
  name_prefix = "agentcore-lambda-sg"
  vpc_id      = local.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "agentcore-lambda-security-group"
    Environment = var.environment
  }
}

resource "aws_security_group" "agentcore_app_sg" {
  count       = var.use_existing_vpc ? 0 : 1
  name_prefix = "agentcore-app-sg"
  vpc_id      = local.vpc_id

  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "agentcore-app-security-group"
    Environment = var.environment
  }
}

resource "aws_security_group" "agentcore_alb_sg" {
  count       = var.use_existing_vpc ? 0 : 1
  name_prefix = "agentcore-alb-sg"
  vpc_id      = local.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "agentcore-alb-security-group"
    Environment = var.environment
  }
}

# Data sources
data "aws_availability_zones" "available" {
  state = "available"
} 