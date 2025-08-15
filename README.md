# AgentCore Marketplace

A robust, scalable marketplace infrastructure for AI agents with human-in-the-loop approval workflows, built using AWS serverless technologies and Terraform.

## 🏗️ Architecture

This project implements a multi-environment, DRY (Don't Repeat Yourself) infrastructure setup using Terraform modules and remote state management.

### Key Components

- **Lambda Functions**: Docker-based functions for approval processing
- **Step Functions**: Orchestrate human-in-the-loop workflows
- **DynamoDB**: Store approval logs, state machine data, and Slack session mappings
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
## 🤖 Slack App Integration

This repo includes a Slack App integration that connects Slack conversations to the AgentCore Gateway.

Features:
- OAuth v2 install flow; bot token stored in AWS Secrets Manager
- Events API handler via API Gateway → Lambda
- Thread persistence by mapping `channel:thread_ts` to `session_id` in DynamoDB
- Incremental streaming back to Slack using message updates
 - Supports `message.*` events and `app_mention` (mention text is cleaned of the `<@bot>` prefix)

Reliability and retries:
- The Events handler now acks within 3 seconds and processes the AgentCore stream asynchronously (set `SLACK_ASYNC=1` in the Slack Lambda env to force async; defaults to auto-enable in Lambda).
- Basic deduplication prevents double-posts if Slack retries the same `event_id`.
- If the AgentCore Gateway returns a transient 404 for the stream cursor, the handler will automatically create a new message cursor and retry once before surfacing an error.

Setup steps:
1. Create a Slack app at `api.slack.com/apps`.
2. In OAuth & Permissions, set a Redirect URL to your API Gateway URL `/oauth/callback`.
3. In Event Subscriptions, set the Request URL to `/events` and subscribe to `message.channels` (and others as needed).
4. Put `client_id`, `client_secret`, and `signing_secret` into Secrets Manager (e.g., `agentcore-dev/slack`).
5. Apply Terraform. Set env vars for the Slack Lambda:
   - `SLACK_SESSIONS_TABLE` = output `slack_sessions_table_name`
   - `SLACK_SECRETS_NAME` = your secret name
   - `AGENTCORE_GATEWAY_URL` = your AgentCore invoke endpoint
    - `SLACK_ASYNC` = `1` to force async processing (recommended for Lambda)
   - Optional: `SLACK_BOT_TOKEN` environment variable can be used as a fallback if Secrets Manager does not contain `bot_token`

The Lambda exchanges OAuth codes, stores the bot token in the same secret, and handles Events (including `app_mention`), invoking the AgentCore Gateway and streaming responses back to Slack. On receipt of an event, it posts an immediate placeholder message to the channel/thread before streaming updates, which helps confirm invocation.

```

### Lambda FastAPI Handler

For the API Lambda, the Docker `api` target uses Mangum. The handler is `src.api.handler` and the base image is `public.ecr.aws/lambda/python:3.11`. You can run locally with RIE:

```bash
docker build --target api -t agentcore-api .
docker run --rm -p 9000:8080 agentcore-api src.api.handler
# invoke locally
curl -s -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" -d '{"rawPath":"/healthz","requestContext":{}}'
```

When deploying via Terraform, the function package type is Image and the runtime will invoke `src.api.handler` automatically.

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
#
# Block Kit (preferred):
# - Create a Slack app with a Bot user and enable Interactivity.
# - Set Interactivity Request URL to: https://<your-api-host>/slack/interactions
# - Add scopes: chat:write
# - Configure environment variables:
#   - SLACK_BOT_TOKEN
#   - SLACK_SIGNING_SECRET
#   - SLACK_CHANNEL_ID
# When SLACK_BOT_TOKEN and SLACK_CHANNEL_ID are set, pending approvals will be posted
# with interactive Approve/Reject buttons. Slack link unfurling is disabled for these
# messages and approvals are received via the interactivity endpoint.

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

## 🔧 Execute Step with AI-Powered MCP Integration

The execute step is a Lambda function that uses AI to interpret natural language requests and execute actions through MCP (Model Context Protocol) servers. This enables the system to perform operations described in plain English rather than requiring structured tool calls.

### Key Features

1. **AI-Powered Action Interpretation** (`src/execute_handler.py`)
   - Accepts natural language action descriptions
   - Uses pydantic-ai with AWS Bedrock models to interpret requests
   - Automatically selects and calls appropriate MCP tools
   - Returns structured execution results

2. **Google MCP Integration**
   - Integrates with Google Workspace Admin Directory API via FastMCP
   - Supports user management operations through natural language
   - Requires both Google OAuth2 credentials and AWS Bedrock access
 - Validated AWS role management via Pydantic models:
   - `admin_role`: matches `^arn:aws:iam::\d{12}:role/[a-zA-Z0-9_-]+$`
   - `identity_provider`: matches `^arn:aws:iam::\d{12}:saml-provider/[a-zA-Z0-9_-]+$`
   - Account ID is derived from the provided ARNs

3. **Streamlined Request Format**
   - No more hardcoded tool names and parameters
   - Simple `action_text` field contains natural language descriptions
   - AI determines which tools to call and with what parameters

### Request Format

**Old format** (structured tool calls):
```json
{
  "request_id": "test-123",
  "execution_timeout": 300
}
```

**New format** (natural language):
```json
{
  "action_text": "Create a new user with email john.doe@example.com, first name John, and last name Doe",
  "execution_timeout": 300
}
```

### Configuration

The execute lambda requires:

1. **AWS Bedrock Access**: Configure AWS credentials and ensure access to Bedrock models
2. **MCP Server Configuration**: 
   - `MCP_HOST`: Hostname of MCP server (default: localhost)
   - `MCP_PORT`: Port of MCP server (default: 8000) 
   - `MCP_AUTH_TOKEN`: Bearer token for MCP server authentication
3. **Google OAuth2 Token**: Base64 encoded JSON file with OAuth2 credentials (for MCP server)

### Example Action Texts

The AI can interpret various natural language requests:

- "Create a new user with email test@example.com"
- "List all users in the example.com domain"
- "Suspend the user account for john.doe@example.com"
- "Get detailed information about user jane.smith@example.com"
- "Add AWS role NMD-Admin for account 123456789012 to user@example.com"
- "Remove AWS access for account 987654321098 from user@example.com"

### Testing

```bash
# Run unit tests for the execute handler
uv run pytest tests/test_execute_handler.py -v

# Test with natural language action
aws stepfunctions start-execution \
  --state-machine-arn $(terraform output -raw step_functions_arn) \
  --input '{"action_text":"Create a new user with email test@example.com, first name Test, and last name User"}'

# Test with Lambda directly
aws lambda invoke \
  --function-name execute-handler \
  --payload '{"action_text":"List all users in example.com domain"}' \
  response.json
```

### Dependencies

Add to your environment:

```bash
# Install pydantic-ai with Bedrock support
uv add "pydantic-ai>=0.0.12"
```

### Security Considerations

- AWS Bedrock API calls are made securely using IAM roles and AWS credentials
- MCP server authentication via Bearer tokens
- All execution results are logged in CloudWatch for auditing
- AI model selection uses cost-efficient models (claude-3-5-haiku)
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

## 🧠 Orchestrator Wrapper

A higher-level orchestrator wraps existing approval/execution handlers and the MCP client without modifying them. It adds:

- Policy engine (deterministic rules) to decide allow/approval/deny
- Step Functions integration to request and await approvals
- Short-term memory to enrich prompts with recent context
- FastAPI API and Click CLI to trigger runs

Modules:

- `src/policy.py`: `ApprovalCategory`, `PolicyRule`, `PolicyEngine`
- `src/memory.py`: `ShortTermMemory`
- `src/orchestrator.py`: `AgentOrchestrator`
- `src/api.py`: FastAPI app (`/agent/run`)
- `src/cli.py`: CLI (`hitl-mcp run`)

### MCP Multi-Server Support

Expose tools from multiple MCP servers in a single conversation by setting `MCP_SERVERS`:

```bash
export MCP_SERVERS="google=/abs/path/google_mcp/google_admin/mcp_server.py;jira=/abs/path/jira_mcp/server.py"
```

The client will qualify tool names by alias (e.g., `jira/create_project`, `jira/bulk_issue_upload`, `google/list_users`) and dispatch calls to the correct server.

CLI example:

```bash
uv run hitl-mcp run \
  --user-id cking \
  --query "create jira project called test-project-cking" \
  --environment dev
```

### Jira MCP

This repo includes a simple Jira MCP server at `jira_mcp/server.py` exposing:
- `create_project`
- `bulk_issue_upload`

Required environment variables for Jira access:

```bash
export JIRA_BASE_URL="https://your-domain.atlassian.net"
export JIRA_EMAIL="service-account@your-domain.com"
export JIRA_API_TOKEN="<api token>"
```

Environment:

- `APPROVAL_SFN_ARN` (optional locally)
- `AWS_REGION`
- `ENVIRONMENT`
- `POLICY_PATH` (optional)

Run API locally:

```bash
uv run uvicorn src.api:app --reload --host 0.0.0.0 --port 8000
```

CLI example:

```bash
uv run hitl-mcp run --user-id alice --query "reset a user's password" --category privileged_write
```

Design references: [runtime example](https://github.com/awslabs/amazon-bedrock-agentcore-samples/blob/main/01-tutorials/01-AgentCore-runtime/01-hosting-agent/01-strands-with-bedrock-model/runtime_with_strands_and_bedrock_models.ipynb), [memory example](https://github.com/awslabs/amazon-bedrock-agentcore-samples/blob/main/01-tutorials/04-AgentCore-memory/01-short-term-memory/01-single-agent/with-strands-agent/personal-agent.ipynb)