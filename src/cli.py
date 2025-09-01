"""Click CLI for orchestrator wrapper."""

from __future__ import annotations

import asyncio
import json

import click
from dotenv import load_dotenv

from .orchestrator import (
    AgentOrchestrator,
    OrchestratorRequest,
    OrchestratorResult,
)
from .config_store import (
    MCPServer,
    put_mcp_servers,
    put_policies,
)
from .policy import DEFAULT_RULES, PolicyRule
from .mcp_client import MCPClient

load_dotenv()


@click.group()
def cli() -> None:
    """AgentCore Orchestrator CLI."""


def _format_result(result: OrchestratorResult) -> str:
    """Format the orchestrator result in a user-friendly way."""
    if result.status == "completed":
        if result.result:
            return f"✅ Task completed successfully!\n\n{result.result}"
        else:
            return "✅ Task completed successfully!"

    elif result.status == "denied":
        return f"❌ Task denied: {result.message or 'Policy violation'}"

    elif result.status == "not_approved":
        return f"⏳ Task not approved: {result.message or 'Approval required but not granted'}"

    elif result.status == "error":
        return f"💥 Error occurred: {result.message or 'Unknown error'}"

    else:
        return f"ℹ️  Status: {result.status}\n{result.message or ''}"


@cli.command("run")
@click.option("--user-id", required=True, help="Requester user id")
@click.option("--query", required=True, help="User query to execute")
@click.option("--tool-name", default=None, help="Preferred tool name")
@click.option("--category", default=None, help="Approval category override")
@click.option("--resource", default=None, help="Target resource identifier")
@click.option(
    "--amount", type=float, default=None, help="Numeric threshold/amount"
)
@click.option("--environment", default=None, help="Environment")
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output raw JSON instead of formatted text",
)
def run_cmd(
    user_id: str,
    query: str,
    tool_name: str | None,
    category: str | None,
    resource: str | None,
    amount: float | None,
    environment: str | None,
    output_json: bool,
) -> None:
    orchestrator = AgentOrchestrator()
    payload = OrchestratorRequest(
        user_id=user_id,
        query=query,
        tool_name=tool_name,
        category=category,
        resource=resource,
        amount=amount,
        environment=environment or "dev",
    )

    async def _run() -> None:
        result = await orchestrator.run(payload)

        if output_json:
            # Output raw JSON for debugging/automation
            click.echo(json.dumps(result.model_dump(), indent=2))
        else:
            # Output user-friendly formatted text
            formatted_output = _format_result(result)
            click.echo(formatted_output)

    asyncio.run(_run())


@cli.command("migrate-config")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be migrated without writing to DynamoDB",
)
@click.option(
    "--include",
    type=click.Choice(["policies", "servers", "all"], case_sensitive=False),
    default="all",
    show_default=True,
    help="Select which config to migrate",
)
def migrate_config_cmd(dry_run: bool, include: str) -> None:
    """Migrate policies from policy.py and MCP servers from .env to config table.

    - Policies are sourced from src.policy.DEFAULT_RULES
    - MCP servers are parsed from MCP_SERVERS env (e.g., "google=/path;a=/p")
    - Writes to the DynamoDB table in CONFIG_TABLE_NAME
    """

    load_dotenv()

    to_migrate_policies = include in ("policies", "all")
    to_migrate_servers = include in ("servers", "all")

    migrated_any = False

    if to_migrate_policies:
        rules: list[PolicyRule] = list(DEFAULT_RULES)
        click.echo(f"Found {len(rules)} policy rule(s) to migrate")
        if not dry_run:
            put_policies(rules)
            migrated_any = True
            click.echo("Policies migrated to config table")

    if to_migrate_servers:
        servers_env = os.getenv("MCP_SERVERS", "").strip()
        mapping = MCPClient._parse_servers_env(servers_env)  # type: ignore[attr-defined]
        servers = [
            MCPServer(alias=alias, path=path, enabled=True)
            for alias, path in mapping.items()
        ]
        click.echo(f"Found {len(servers)} MCP server(s) to migrate")
        if not dry_run:
            put_mcp_servers(servers)
            migrated_any = True
            click.echo("MCP servers migrated to config table")

    if dry_run and (to_migrate_policies or to_migrate_servers):
        click.echo("Dry run complete (no writes performed)")

    if not migrated_any and not dry_run:
        click.echo(
            "Nothing migrated. Check --include selection or source data."
        )


if __name__ == "__main__":
    cli()
