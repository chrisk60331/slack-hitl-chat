## AgentCore Marketplace

### What it does

Human-in-the-loop AI orchestration for executing tasks via MCP tools (Google, Jira, etc.), with policy checks, approval flows, and a FastAPI gateway. Includes a CLI for direct runs.

- Approval Lambda (`src/approval_handler.lambda_handler`): Creates/updates approval requests, writes to DynamoDB, and sends Slack/SNS notifications; also handles approve/reject callbacks.
- Execute Lambda (`src/execute_handler.lambda_handler`): Executes approved actions via MCP using the stored request, and updates completion status/message in DynamoDB.
- Completion Notifier Lambda (`src/completion_notifier.lambda_handler`): Posts paginated, threaded Slack replies with the final execution result.
- Slack Gateway Lambda (`src/slack_lambda.lambda_handler`): Handles Slack OAuth callback and Events API, verifies signatures, dedupes retries, and triggers the approval/execution workflow.
- API Lambda (`src/api:handler`): FastAPI app packaged with Mangum; exposes `/agent/run`, `/config/*`, `/audit/approvals`, `/slack/interactions`, and mounts the Admin UI under `/admin`.

### How to run

Prereqs: Python 3.11+, UV installed, AWS credentials configured (for Bedrock), and `AWS_REGION` set.

Run API (Docs & Admin): 
```bash
uv run uvicorn src.api:app --host 0.0.0.0 --port 8000 --reload (Docs: http://localhost:8000/docs, Admin: http://localhost:8000/admin)
```
Run CLI: 
```bash
uv run hitl-mcp run --user-id <your email here> --environment dev --query "<your query here>"
```

### How to test

```bash
uv run pytest -q
```
