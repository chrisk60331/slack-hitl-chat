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

### Styling (Tailwind CSS)

For the lightweight Admin templates under `src/templates`, Tailwind CSS is included via the Play CDN for simplicity. No build step is required.

- Added to each template `<head>`:
  - `<meta name="viewport" content="width=device-width, initial-scale=1"/>`
  - `<script src="https://cdn.tailwindcss.com"></script>`
- Minimal classes (e.g., `class="min-h-screen bg-gray-50 text-gray-900 p-8"`) were applied to bodies.

Note: For production-hardening or custom design tokens, replace the CDN with a proper Tailwind build (CLI or PostCSS) and a base layout to avoid duplication across templates.

Landing page was refreshed with a Tailwind hero and navigation cards in `src/templates/index.html`. Subpages (`servers.html`, `policies.html`, `approvals.html`) are styled with Tailwind wrappers, tables, and controls. The approvals table supports column resizing with a minimal inline script.

Approvals page enhancements:
- Client-side search (free text) and status filter
- Click-to-sort on any header (timestamp sorts by date)

### Admin UI: Approvals table column resizing

The Approvals page (`src/templates/approvals.html`) supports mouse-based column resizing:

- Hover near the right edge of a column header until the resize cursor appears, then drag.
- The width applies to the header and corresponding body cells.
- Minimum width is constrained to 80px to maintain readability.

This is implemented with a minimal inline JS script and does not require external dependencies.
