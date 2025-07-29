# Use AWS Lambda Python 3.11 base image
FROM public.ecr.aws/lambda/python:3.11

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set work directory
WORKDIR ${LAMBDA_TASK_ROOT}

# Copy pyproject.toml first for better caching
COPY pyproject.toml README.md ./
COPY src/ ./agentcore_marketplace/
COPY src/ ./src/
RUN pip install -e .


# Set the Lambda handler
CMD ["src.approval_handler.lambda_handler"] 