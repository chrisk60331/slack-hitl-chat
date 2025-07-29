# AgentCore Marketplace

AWS Bedrock AgentCore-based human-in-the-loop system using Docker containers and Terraform for infrastructure.

## Features

- **Docker-based Lambda Functions**: Uses container images instead of zip files for better dependency management
- **UV Package Manager**: Fast Python package installation and dependency resolution  
- **Terraform Infrastructure**: Complete AWS infrastructure as code
- **Human-in-the-Loop Workflow**: Step Functions orchestrated approval process
- **MCP Server Integration**: Native Model Context Protocol server with HITL approval middleware
- **Risk-based Approval**: Intelligent risk evaluation with configurable approval thresholds
- **Multiple Notification Channels**: Slack, Microsoft Teams, and SNS support
- **DynamoDB Logging**: Persistent approval logs with TTL
- **VPC Support**: Optional deployment in existing VPC infrastructure
- **CLI Management**: Command-line tools for configuration and monitoring

## Architecture

The system consists of:

1. **MCP Server**: Human-in-the-Loop middleware that intercepts and evaluates MCP requests
2. **Lambda Function** (Docker container): Processes approval requests and sends notifications
3. **Step Functions**: Orchestrates the human-in-the-loop workflow
4. **DynamoDB**: Stores approval logs and state machine data
5. **ECR Repository**: Stores the Lambda Docker images
6. **SNS/Slack/Teams**: Notification channels for approvals
7. **Risk Evaluator**: Intelligent assessment of operation risk levels

## Prerequisites

- AWS CLI configured with appropriate permissions
- Terraform >= 1.0
- Docker
- UV (Python package manager)
- Python >= 3.11

## Quick Start

1. **Check Dependencies**:
   ```bash
   ./build_and_deploy.sh check
   ```

2. **Configure Variables**:
   ```bash
   cp terraform/terraform.tfvars.example terraform/terraform.tfvars
   # Edit terraform.tfvars with your settings
   ```

3. **Deploy Infrastructure**:
   ```bash
   ./build_and_deploy.sh deploy
   ```

4. **Configure MCP Server**:
   ```bash
   # Generate MCP configuration
   uv run hitl-mcp generate-config --lambda-url $LAMBDA_FUNCTION_URL --output mcp-config.json
   
   # Start HITL MCP server
   uv run hitl-mcp serve --lambda-url $LAMBDA_FUNCTION_URL
   ```

## Deployment Options

### Full Deployment
```bash
# Check dependencies, initialize Terraform, plan, and apply
./build_and_deploy.sh deploy
```

### Step-by-Step Deployment
```bash
# 1. Check dependencies
./build_and_deploy.sh check

# 2. Build Docker image locally (optional)
./build_and_deploy.sh build

# 3. Initialize Terraform
./build_and_deploy.sh init

# 4. Plan deployment
./build_and_deploy.sh plan

# 5. Apply deployment
./build_and_deploy.sh apply
```

### Local Testing
```bash
# Build and test Docker image locally
./build_and_deploy.sh test
```

## Configuration

### Terraform Variables

Create `terraform/terraform.tfvars`:

```hcl
aws_region = "us-east-1"
environment = "prod"

# Notification webhooks (optional)
slack_webhook_url = "https://hooks.slack.com/services/..."
teams_webhook_url = "https://outlook.office.com/webhook/..."

# VPC configuration (if using existing VPC)
use_existing_vpc = true
vpc_id = "vpc-xxxxxxxxx"
private_subnet_ids = ["subnet-xxxxxxxx", "subnet-yyyyyyyy"]
lambda_security_group_id = "sg-xxxxxxxxx"

# Lambda configuration
lambda_timeout = 30
lambda_memory_size = 256
```

### Environment Variables

The Lambda function uses these environment variables (automatically configured):

- `TABLE_NAME`: DynamoDB table name for approval logs
- `SLACK_WEBHOOK_URL`: Slack webhook URL for notifications
- `TEAMS_WEBHOOK_URL`: Microsoft Teams webhook URL
- `SNS_TOPIC_ARN`: SNS topic ARN for notifications

## Docker Build Process

The deployment uses Docker containers for Lambda functions:

1. **Base Image**: AWS Lambda Python 3.11 runtime
2. **Package Manager**: UV for fast dependency installation
3. **Dependencies**: Installed from `pyproject.toml`
4. **Registry**: Amazon ECR for image storage
5. **Deployment**: Terraform manages the complete lifecycle

### Dockerfile Features

- Multi-stage build with UV package manager
- Optimized layer caching
- AWS Lambda runtime compatibility
- Automatic dependency resolution from pyproject.toml

## MCP Server Usage

### Starting the HITL MCP Server

```bash
# Using CLI with options
uv run hitl-mcp serve \
  --lambda-url https://your-lambda-url.aws.com \
  --approver admin \
  --timeout 3600 \
  --auto-approve-low-risk

# Using environment variables
export LAMBDA_FUNCTION_URL=https://your-lambda-url.aws.com
export DEFAULT_APPROVER=security_team
uv run hitl-mcp serve

# Using configuration file
uv run hitl-mcp init-config --output hitl-config.json
# Edit hitl-config.json with your settings
uv run hitl-mcp serve --config-file hitl-config.json
```

### MCP Configuration

Generate MCP client configuration:

```bash
uv run hitl-mcp generate-config \
  --lambda-url https://your-lambda-url.aws.com \
  --table-name your-dynamodb-table \
  --sns-topic-arn arn:aws:sns:region:account:topic \
  --output mcp-hitl-config.json
```

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "hitl-approval": {
      "command": "uv",
      "args": ["run", "python", "-m", "src.mcp_server"],
      "cwd": "/path/to/agentcore_marketplace",
      "env": {
        "LAMBDA_FUNCTION_URL": "https://your-lambda-url.aws.com",
        "DEFAULT_APPROVER": "admin",
        "APPROVAL_TIMEOUT": "1800"
      }
    }
  }
}
```

### Risk Evaluation

The system automatically evaluates risk levels for all MCP requests:

- **LOW**: Read-only operations (tools/list, resources/list)
- **MEDIUM**: Standard operations with moderate risk  
- **HIGH**: File operations, network requests, shell commands
- **CRITICAL**: System files, destructive commands, database operations

### Managing Approvals

```bash
# Check approval status
uv run hitl-mcp check-approval \
  --lambda-url https://your-lambda-url.aws.com \
  --request-id abc123

# Monitor via MCP tools
# Use approval_status tool in your MCP client
# Use list_pending_approvals tool to see pending requests
```

## API Usage

### Approval Request Format

```json
{
  "request_id": "unique-request-id",
  "action": "approve|reject|pending",
  "requester": "user-id",
  "agent_prompt": "Original agent prompt",
  "proposed_action": "Action to be taken",
  "reason": "Reason for decision",
  "approver": "approver-id"
}
```

### Response Format

```json
{
  "request_id": "unique-request-id",
  "status": "approve|reject|pending",
  "timestamp": "2024-01-01T00:00:00Z",
  "notification_sent": true
}
```

### MCP Request Flow

1. **Request Interception**: MCP server intercepts all tool calls
2. **Risk Evaluation**: Automatic assessment of operation risk level
3. **Approval Decision**: High/Critical risk operations require approval
4. **Notification**: Approval requests sent via configured channels
5. **Response**: Operation proceeds only after approval granted

## Development

### Project Structure

```
agentcore_marketplace/
├── agentcore_marketplace/          # Core Python package
├── lambda/                         # Lambda function code
├── terraform/                      # Infrastructure as code
├── Dockerfile                      # Container definition
├── pyproject.toml                  # Python dependencies
├── build_and_deploy.sh            # Deployment script
└── README.md                       # Documentation
```

### Adding Dependencies

Add dependencies to `pyproject.toml`:

```toml
dependencies = [
    "new-package>=1.0.0",
]
```

The Docker build will automatically install them using UV.

### Local Development

1. **Install UV**:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Create Virtual Environment**:
   ```bash
   uv venv
   source .venv/bin/activate  # or .venv\Scripts\activate on Windows
   ```

3. **Install Dependencies**:
   ```bash
   uv pip install -e .
   ```

4. **Run Tests**:
   ```bash
   uv run pytest
   uv run pytest tests/test_mcp_server.py  # MCP server tests
   uv run pytest tests/test_cli.py         # CLI tests
   ```

5. **Development Commands**:
   ```bash
   # Start development MCP server
   uv run python -m src.mcp_server
   
   # Run CLI commands
   uv run hitl-mcp --help
   uv run hitl-mcp serve --debug
   
   # Format and lint code
   uv run ruff format .
   uv run ruff check .
   ```

## Monitoring and Logging

- **CloudWatch Logs**: Lambda execution logs
- **DynamoDB**: Approval request history
- **ECR**: Container image scanning and lifecycle policies
- **Step Functions**: Workflow execution history

## Cleanup

To destroy all resources:

```bash
./build_and_deploy.sh destroy
```

## Contributing

1. Follow the workspace rules defined in the project
2. Write tests for new functions
3. Add type hints and docstrings
4. Update documentation for new features
5. Use ruff for linting and formatting

## License

MIT License - see LICENSE file for details. 