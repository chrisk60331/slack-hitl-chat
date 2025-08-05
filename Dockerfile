# Multi-stage Dockerfile for AgentCore Marketplace Lambda functions

# Base stage with common setup
FROM public.ecr.aws/lambda/python:3.11 AS base

# Install uv for faster dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set work directory
WORKDIR ${LAMBDA_TASK_ROOT}

# Copy pyproject.toml first for better caching
COPY pyproject.toml README.md ./

# Copy the main application source
COPY src/ ./src/

# Install main application dependencies
RUN uv pip install --system --no-cache-dir -e .

# Approval handler Lambda target
FROM base AS approval
CMD ["src.approval_handler.lambda_handler"]

# Execute handler Lambda target
FROM base AS execute

# Google MCP dependencies are now included in the main pyproject.toml
# The google_admin package is now in src/google_admin/

CMD ["src.execute_handler.lambda_handler"] 