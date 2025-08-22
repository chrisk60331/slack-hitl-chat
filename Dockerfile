# Multi-stage Dockerfile for AgentCore Marketplace Lambda functions

# Base stage with common setup
FROM public.ecr.aws/lambda/python:3.11 AS base

# Install uv for faster dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set work directory
WORKDIR ${LAMBDA_TASK_ROOT}

RUN yum update -y && yum install -y gcc unzip curl
# Copy pyproject.toml first for better caching
COPY pyproject.toml README.md ./

# Copy the main application source
RUN mkdir src

# Install main application dependencies
RUN uv pip install --system --no-cache-dir -e .

RUN rm -rf src
COPY src/ ./src/

# Approval handler Lambda target
FROM base AS approval
CMD ["src.approval_handler.lambda_handler"]

# Execute handler Lambda target
FROM base AS execute
COPY .env ./
WORKDIR "/var/task"
COPY JIRA_Tickets__-_JIRA_tickets_template.csv /var/task/
COPY google_mcp/ /var/task/google_mcp/
COPY google_mcp/google_calendar/ /var/task/google_calendar/
COPY google_mcp/google_admin/ ./google_admin/
COPY totp_mcp/ ./totp_mcp/
COPY jira_mcp/ ./jira_mcp/
CMD ["src.execute_handler.lambda_handler"] 

# Slack handler Lambda target
FROM base AS slack
COPY .env ./
COPY google_mcp/ ./google_mcp/
COPY google_mcp/google_calendar/ ./google_calendar/
COPY google_mcp/google_admin/ ./google_admin/
COPY totp_mcp/ ./totp_mcp/
COPY jira_mcp/ ./jira_mcp/
CMD ["src.slack_lambda.lambda_handler"]

# Completion notifier Lambda target
FROM base AS completion
CMD ["src.completion_notifier.lambda_handler"]

# FastAPI API (Lambda Web Adapter)
FROM base AS api
# For Lambda, use Mangum handler; no need for web adapter
ENV PORT=8080
WORKDIR "/var/task"
COPY .env ./
COPY google_mcp/ ./google_mcp/
CMD ["src.api.handler"]