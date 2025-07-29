# Use AWS Lambda Python 3.11 base image
FROM public.ecr.aws/lambda/python:3.11

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set work directory
WORKDIR ${LAMBDA_TASK_ROOT}

# Install core dependencies directly
RUN uv pip install --system --no-cache-dir \
    boto3>=1.34.0 \
    botocore>=1.34.0 \
    pydantic>=2.5.0 \
    requests>=2.31.0

# Copy source code
COPY src/ ./src/

# Set the Lambda handler
CMD ["src.approval_handler.lambda_handler"] 