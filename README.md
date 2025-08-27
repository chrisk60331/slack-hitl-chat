# AgentCore Marketplace

A robust, scalable infrastructure for AI agents with human-in-the-loop approval workflows, built using AWS serverless technologies and Terraform.

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
cd terraform/bootstrap
terraform init
terraform apply
```

This creates:
- S3 bucket for storing Terraform state files
- DynamoDB table for state locking
- Proper encryption and security configurations

### 2. Deploy to Development Environment

```bash
cd terraform/environments/dev
terraform apply
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

### Slack threaded replies and Block Kit

Slack interactions now always reply in a thread anchored to the user's original message. The initial bot reply includes `thread_ts` so all subsequent updates and messages remain scoped to that thread for clear request↔response mapping.

When an approved action completes, the completion notifier updates the original Slack message. If the execution result contains a `blocks` array (Slack Block Kit), those blocks will be used. Otherwise, a simple mrkdwn section block is synthesized from the result text so updates always use Block Kit.

Set the bot token:

```bash
export SLACK_BOT_TOKEN=xoxb-...
```

### Building and Testing Lambda Functions

```bash
# Build Docker image locally
docker build -t agentcore-hitl-approval .

# Test locally (if you have lambda runtime emulator)
docker run -p 9000:8080 agentcore-hitl-approval
```

## 🌐 Google MCP Integrations

This project includes comprehensive Google Workspace MCP (Model Context Protocol) integrations for seamless AI agent interactions with Google services.

### Google Admin MCP

Provides administrative capabilities for Google Workspace domains:

- **User Management**: Create, list, get, suspend/unsuspend users
- **Role Management**: Add/remove AWS roles from user profiles
- **Domain Operations**: List users by domain with filtering and ordering

**Tools Available:**
- `list_users` - List users in a domain
- `add_user` - Create new users
- `get_user` - Get detailed user information
- `suspend_user` / `unsuspend_user` - Manage user accounts
- `get_amazon_roles` - Retrieve AWS roles from user profiles
- `add_amazon_role` / `remove_amazon_role` - Manage AWS role assignments

### Google Calendar MCP

Enables calendar management and scheduling operations:

- **Event Management**: Create, read, update, delete calendar events
- **Calendar Operations**: List calendars, manage availability
- **Scheduling**: Handle recurring events and timezone conversions

### Google Drive MCP

#### Search query behavior

The `search_documents` tool now interprets the free-text `query` using Drive v3 fields:

- It builds `(name contains 'QUERY' or fullText contains 'QUERY') and trashed=false` by default
- When `file_types` are provided, they are appended as an `or` group of `mimeType` filters
- `owner` adds a `'owner@example.com' in owners` filter
- `include_shared=False` adds `'me' in owners`

Single quotes in `query` are escaped for the Drive query syntax.

Comprehensive document and file management capabilities:

- **Document Search**: Advanced search with file type filtering, owner filtering, and shared document inclusion
- **Document Creation**: Create Google Docs, Sheets, Slides, and folders
- **Document Management**: Get, update, and delete documents with permission management
- **Folder Operations**: List and navigate folder structures

**Tools Available:**
- `search_documents` - Search for documents using various criteria
- `create_document` - Create new documents, spreadsheets, presentations, or folders
- `get_document` - Retrieve document metadata and optional content
- `update_document` - Update document properties and content
- `delete_document` - Delete documents or move to trash
- `list_folders` - List folders with optional parent folder filtering
- `list_drives` - List shared drives accessible to the service account (optional name filter)
- `copy_document` - Copy a document/file, optionally rename and place into a destination folder

#### Updating Google Docs Content

The `update_document` tool supports updating the title, permissions, and the full text content of Google Docs. Content updates require the Google Docs API.

- Ensure your OAuth scopes include:
  - `https://www.googleapis.com/auth/drive`
  - `https://www.googleapis.com/auth/drive.file`
  - `https://www.googleapis.com/auth/documents`

If content updates appear to succeed but no changes are visible in the Doc, verify that the Docs scope is granted to the service account and domain-wide delegation (if used) includes this scope. You can list granted scopes via:

```bash
uv run python google_mcp/google_admin/list_scopes.py
```

**Supported Document Types:**
- Google Docs (`document`)
- Google Sheets (`spreadsheet`) 
- Google Slides (`presentation`)
- Folders (`folder`)
- PDF files (`pdf`)

**Search Capabilities:**
- Full-text search across document names and content
- File type filtering (document, spreadsheet, presentation, folder, pdf)
- Owner-based filtering
- Shared document inclusion/exclusion
- Configurable result limits

**Permission Management:**
- Share documents with specific users
- Set read/write/owner permissions
- Manage access control lists

**Shared Drives:**
- List shared drives your service account can access
- Optional name filter matched with `name contains 'QUERY'`

### Configuration

All Google MCP servers use the same authentication configuration:

```bash
# Required environment variables
GOOGLE_TYPE=service_account
GOOGLE_PROJECT_ID=your-project-id
GOOGLE_PRIVATE_KEY_ID=your-private-key-id
GOOGLE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
GOOGLE_CLIENT_EMAIL=your-service-account@your-project.iam.gserviceaccount.com
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_AUTH_URI=https://accounts.google.com/o/oauth2/auth
GOOGLE_TOKEN_URI=https://oauth2.googleapis.com/token
GOOGLE_AUTH_PROVIDER_X509_CERT_URL=https://www.googleapis.com/oauth2/v1/certs
GOOGLE_CLIENT_X509_CERT_URL=https://www.googleapis.com/robot/v1/metadata/x509/your-service-account%40your-project.iam.gserviceaccount.com
GOOGLE_UNIVERSE_DOMAIN=googleapis.com
GOOGLE_ADMIN_EMAIL=admin@yourdomain.com
```

### MCP Multi-Server Support

Expose tools from multiple MCP servers in a single conversation by setting `MCP_SERVERS`:

```bash
export MCP_SERVERS="google=/abs/path/google_mcp/google_admin/mcp_server.py;jira=/abs/path/jira_mcp/server.py;calendar=/abs/path/google_mcp/google_calendar/mcp_server.py;totp=/abs/path/totp_mcp/mcp_server.py"
```

The client will qualify tool names by alias (e.g., `jira/create_project`, `jira/bulk_issue_upload`, `google/list_users`) and dispatch calls to the correct server.

CLI example:

```bash
uv run hitl-mcp run \
  --user-id cking \
  --query "create jira project called test-project-cking" \
  --environment dev
```
