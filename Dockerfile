# Multi-stage Dockerfile for AgentCore Marketplace Lambda functions

# Base stage with common setup
FROM public.ecr.aws/lambda/python:3.11 AS test

FROM public.ecr.aws/lambda/python:3.11 AS base
# Base stage with common setup

# Install uv for faster dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set work directory
WORKDIR ${LAMBDA_TASK_ROOT}
RUN yum update -y && yum install -y tar
RUN yum install -y gzip
RUN yum install -y glibc
# Install build tools and unzip for AWS CLI
RUN yum install -y gcc gcc-c++ make openssl-devel pkgconfig unzip curl

# Install Rust (for Cargo) non-interactively
ENV RUSTUP_HOME=/usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
ENV PATH="/usr/local/cargo/bin:${PATH}"

# Install AWS CLI v2
RUN curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "/tmp/awscliv2.zip" \
 && unzip -q /tmp/awscliv2.zip -d /tmp \
 && /tmp/aws/install \
 && rm -rf /tmp/aws /tmp/awscliv2.zip

# Install use_aws_mcp via Cargo
RUN cargo install use_aws_mcp 
RUN $CARGO_HOME/bin/use_aws_mcp --help
# Install nvm into a world-readable location (not under /root)
ENV NVM_DIR=/usr/local/nvm
RUN mkdir -p $NVM_DIR && chmod 755 $NVM_DIR
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash

# install node
ENV NODE_VERSION=16
RUN bash -c "source $NVM_DIR/nvm.sh && nvm install $NODE_VERSION"
# Ensure nvm directory and installed node are world-readable/executable for Lambda user
RUN chmod -R a+rX $NVM_DIR && find $NVM_DIR -type d -exec chmod 755 {} +

RUN bash -c "source $NVM_DIR/nvm.sh && nvm -v"
RUN bash -c "source $NVM_DIR/nvm.sh && node -v"
RUN bash -c "source $NVM_DIR/nvm.sh && npx -v"
# Expose node/npm/npx to the non-root Lambda runtime user via system PATH
RUN bash -lc "source $NVM_DIR/nvm.sh \
 && NODE_BIN_DIR=\$(dirname \$(nvm which default)) \
 && ln -sf \$NODE_BIN_DIR/node /usr/local/bin/node \
 && ln -sf \$NODE_BIN_DIR/npm /usr/local/bin/npm \
 && ln -sf \$NODE_BIN_DIR/npx /usr/local/bin/npx"
# Verify availability without sourcing nvm (system PATH)
RUN node -v && npm -v && npx -v
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
COPY google_mcp/gdrive_mcp/ ./gdrive_mcp/
COPY totp_mcp/ ./totp_mcp/
COPY jira_mcp/ ./jira_mcp/
COPY gif_mcp/ ./gif_mcp/
ENV PATH="/usr/local/cargo/bin:/usr/local/bin:${PATH}"
CMD ["src.execute_handler.lambda_handler"] 

# Slack handler Lambda target
FROM base AS slack
COPY .env ./
COPY google_mcp/ ./google_mcp/
COPY google_mcp/google_calendar/ ./google_calendar/
COPY google_mcp/google_admin/ ./google_admin/
COPY google_mcp/gdrive_mcp/ ./gdrive_mcp/
COPY totp_mcp/ ./totp_mcp/
COPY jira_mcp/ ./jira_mcp/
COPY gif_mcp/ ./gif_mcp/
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