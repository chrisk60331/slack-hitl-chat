# AgentCore Marketplace

A robust, scalable marketplace infrastructure for AI agents with human-in-the-loop approval workflows, built using AWS serverless technologies and Terraform.

## 🏗️ Architecture

This project implements a multi-environment, DRY (Don't Repeat Yourself) infrastructure setup using Terraform modules and remote state management.

### Key Components

- **Lambda Functions**: Docker-based functions for approval processing
- **Step Functions**: Orchestrate human-in-the-loop workflows
- **DynamoDB**: Store approval logs and state machine data
- **SNS**: Notifications and messaging
- **EventBridge**: Event-driven workflow triggers
- **VPC**: Network isolation and security
- **IAM**: Fine-grained access control

## 📁 Project Structure

```
agentcore_marketplace/
├── src/                           # Application source code
│   ├── __init__.py
│   ├── approval_handler.py        # Lambda function handler
│   ├── execute_handler.py         # MCP execution handler
│   ├── google_admin/              # Google Workspace MCP integration
│   │   ├── config/                # Google API configuration
│   │   ├── models/                # Request/response models
│   │   ├── services/              # Business logic
│   │   ├── repositories/          # Google API client
│   │   ├── utils/                 # Helper utilities
│   │   └── mcp_server.py          # FastMCP server implementation
├── terraform/                     # Infrastructure as Code
│   ├── bootstrap/                 # Remote state backend setup
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   └── terraform.tfvars
│   ├── modules/                   # Reusable Terraform modules
│   │   ├── networking/            # VPC, subnets, security groups
│   │   ├── iam/                   # Roles and policies
│   │   ├── dynamodb/              # Database tables
│   │   ├── lambda/                # Function and ECR setup
│   │   └── stepfunctions/         # State machines and EventBridge
│   ├── environments/              # Environment-specific configurations
│   │   ├── dev/                   # Development environment
│   │   ├── staging/               # Staging environment
│   │   └── prod/                  # Production environment
│   └── scripts/                   # Deployment automation
│       └── deploy.sh
├── tests/                         # Unit tests
├── Dockerfile                     # Container definition
├── pyproject.toml                # Python project configuration
└── README.md
```

## 🚀 Quick Start

### Prerequisites

- [Terraform](https://terraform.io/) >= 1.0
- [AWS CLI](https://aws.amazon.com/cli/) configured with appropriate credentials
- [Docker](https://docker.com/) for building Lambda images
- [UV](https://github.com/astral-sh/uv) for Python dependency management

### 1. Bootstrap Remote State Backend

First, deploy the shared infrastructure for Terraform remote state:

```bash
# Deploy S3 bucket and DynamoDB table for remote state
terraform/scripts/deploy.sh bootstrap apply
```

This creates:
- S3 bucket for storing Terraform state files
- DynamoDB table for state locking
- Proper encryption and security configurations

### 2. Deploy to Development Environment

```bash
# Plan development deployment
terraform/scripts/deploy.sh dev plan

# Apply development deployment
terraform/scripts/deploy.sh dev apply
```

### 3. Deploy to Other Environments

```bash
# Staging environment
terraform/scripts/deploy.sh staging plan
terraform/scripts/deploy.sh staging apply

# Production environment  
terraform/scripts/deploy.sh prod plan
terraform/scripts/deploy.sh prod apply
```

## 🔧 Configuration

### Environment-Specific Settings

Each environment has its own configuration in `terraform/environments/{env}/terraform.tfvars`:

#### Development (dev)
- VPC CIDR: `10.0.0.0/16`
- Lambda: 256MB memory, 30s timeout
- Basic security settings
- Bedrock Guardrails: Disabled

#### Staging (staging)
- VPC CIDR: `10.1.0.0/16`
- Lambda: 512MB memory, 60s timeout
- Enhanced monitoring
- Bedrock Guardrails: Enabled

#### Production (prod)
- VPC CIDR: `10.2.0.0/16`
- Lambda: 1024MB memory, 120s timeout
- High availability configuration
- Bedrock Guardrails: Enabled
- Extended Step Functions timeout (4 hours)

### Custom Configuration

To customize any environment, edit the corresponding `terraform.tfvars` file:

```hcl
# terraform/environments/dev/terraform.tfvars

# AWS Configuration
aws_region = "us-east-1"
environment = "dev"

# VPC Configuration
use_existing_vpc = false  # Set to true to use existing VPC
# vpc_id = "vpc-xxxxxxxxx"  # Uncomment if using existing VPC

# Lambda Configuration
lambda_timeout = 30
lambda_memory_size = 256

# Notification Configuration
# slack_webhook_url = "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
# teams_webhook_url = "https://outlook.office.com/webhook/YOUR/TEAMS/WEBHOOK"

# Bedrock Configuration
# enable_bedrock_guardrails = true
# bedrock_guardrail_id = "your-guardrail-id"
```

## 🛠️ Development

### Local Setup

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Run linting
uv run ruff check

# Run formatting
uv run ruff format
```

### Building and Testing Lambda Functions

```bash
# Build Docker image locally
docker build -t agentcore-hitl-approval .

# Test locally (if you have lambda runtime emulator)
docker run -p 9000:8080 agentcore-hitl-approval
```

## 📊 Monitoring and Observability

### CloudWatch Integration

- **Lambda Logs**: `/aws/lambda/{environment}_hitl_approval`
- **Step Functions Logs**: `/aws/stepfunctions/{environment}-hitl-workflow`
- **Retention**: 14 days (configurable)

### Key Metrics to Monitor

- Lambda execution duration and errors
- Step Functions execution success/failure rates
- DynamoDB read/write capacity and throttling
- SNS message delivery rates

## 🔐 Security

### IAM Best Practices

- Least privilege access for all roles
- Separate roles for Lambda, Step Functions, and application components
- Environment-specific resource isolation
- Encrypted data at rest and in transit

### Network Security

- Private subnets for Lambda functions
- Security groups with minimal required access
- VPC endpoints for AWS service communication
- Optional: Use existing VPC for enhanced security controls

## 🚧 Advanced Usage

### Using Existing VPC

To deploy into an existing VPC, configure the following in your `terraform.tfvars`:

```hcl
use_existing_vpc = true
vpc_id = "vpc-xxxxxxxxx"
private_subnet_ids = ["subnet-xxxxxxxxx", "subnet-yyyyyyyyy"]
public_subnet_ids = ["subnet-aaaaaaaaa", "subnet-bbbbbbbbb"]
lambda_security_group_id = "sg-xxxxxxxxx"
app_security_group_id = "sg-yyyyyyyyy"
alb_security_group_id = "sg-zzzzzzzzz"
```

### Multi-Region Deployment

To deploy to multiple regions:

1. Copy environment folder and update region configuration
2. Update backend configuration with region-specific bucket
3. Deploy bootstrap infrastructure in new region first

### Custom Modules

The modular structure allows easy customization:

```hcl
# Add custom module
module "custom_component" {
  source = "../../modules/custom"
  
  name_prefix = local.name_prefix
  tags        = local.common_tags
}
```

## 🔄 Deployment Workflow

### Recommended Deployment Flow

1. **Bootstrap** (one time): `terraform/scripts/deploy.sh bootstrap apply`
2. **Development**: `terraform/scripts/deploy.sh dev apply`
3. **Testing**: Run integration tests against dev environment
4. **Staging**: `terraform/scripts/deploy.sh staging apply`
5. **Production**: `terraform/scripts/deploy.sh prod apply`

### Destroying Infrastructure

```bash
# Destroy specific environment
terraform/scripts/deploy.sh dev destroy

# Destroy bootstrap (WARNING: This makes all state files inaccessible)
terraform/scripts/deploy.sh bootstrap destroy
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes and add tests
4. Run linting and formatting: `uv run ruff check && uv run ruff format`
5. Ensure tests pass: `uv run pytest`
6. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Troubleshooting

### Common Issues

#### 1. Backend Not Found
```
Error: Backend configuration not found
```
**Solution**: Deploy bootstrap infrastructure first: `terraform/scripts/deploy.sh bootstrap apply`

#### 2. Docker Build Fails
```
Error: Failed to build Docker image
```
**Solution**: Ensure Docker is running and you have permissions to access ECR

#### 3. Permission Denied
```
Error: Access denied to S3 bucket
```
**Solution**: Verify AWS credentials have necessary permissions for S3 and DynamoDB

#### 4. State Lock
```
Error: Error acquiring the state lock
```
**Solution**: Check DynamoDB table for stuck locks or wait for concurrent operation to complete

### Getting Help

- Check CloudWatch logs for Lambda and Step Functions
- Review Terraform plan output before applying
- Use `terraform/scripts/deploy.sh {env} plan` to preview changes
- Ensure all required variables are set in `terraform.tfvars`

## 🔧 Execute Step with Google MCP Integration

The execute step is a Lambda function that loads an MCP (Model Context Protocol) server and executes approved actions. This enables the system to actually perform the operations that were approved through the human-in-the-loop workflow.

### Components

1. **Execute Lambda Function** (`src/execute_handler.py`)
   - Loads Google MCP server with Google Workspace Admin tools
   - Executes approved actions (add user, suspend user, etc.)
   - Reports execution results back to the workflow

2. **Google MCP Integration**
   - Integrates with Google Workspace Admin Directory API
   - Provides tools for user management operations
   - Requires Google OAuth2 credentials

3. **Enhanced Step Functions Workflow**
   - Added execute step after approval is granted
   - Handles execution success/failure states
   - Provides full end-to-end automation

### Deployment

Deploy the execute step with Google MCP integration:

```bash
# Set your Google OAuth2 token (base64 encoded)
export GOOGLE_TOKEN_JSON="your_base64_encoded_google_oauth2_token"

# Run the deployment script
./deploy_execute_lambda.sh
```

### Configuration

The execute lambda requires:

1. **Google OAuth2 Token**: Base64 encoded JSON file with OAuth2 credentials
2. **DynamoDB Access**: To read approval requests and update execution status
3. **VPC Configuration**: Optional, for secure network access

### Available Tools

The Google MCP server provides the following tools:

- **list_users**: List users in a Google Workspace domain
- **add_user**: Create new users with secure random passwords
- **get_user**: Get detailed user information
- **suspend_user**: Suspend user accounts
- **unsuspend_user**: Unsuspend user accounts

### Testing

```bash
# Run unit tests for the execute handler
uv run pytest tests/test_execute_handler.py -v

# Test the complete workflow
aws stepfunctions start-execution \
  --state-machine-arn $(terraform output -raw step_functions_arn) \
  --input '{"request_id":"test-request","tool_name":"add_user","parameters":{"primary_email":"test@example.com","first_name":"Test","last_name":"User"}}'
```

### Security Considerations

- Google OAuth2 credentials are stored securely as environment variables
- All user creation requires password change on first login
- Execution results are logged in CloudWatch for auditing
- VPC configuration provides network isolation

## 🎯 Roadmap

- [ ] Multi-region support with cross-region replication
- [ ] Enhanced monitoring with custom CloudWatch dashboards
- [ ] Automated testing pipeline with GitHub Actions
- [ ] Blue-green deployment support
- [ ] Cost optimization recommendations
- [ ] Enhanced security scanning and compliance checks
- [x] Execute step with MCP server integration
- [ ] Support for additional MCP servers and tools
- [ ] Enhanced error handling and retry mechanisms 