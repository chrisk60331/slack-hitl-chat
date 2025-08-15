"""Click CLI for orchestrator wrapper."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import click

from .orchestrator import AgentOrchestrator, OrchestratorRequest
from dotenv import load_dotenv

load_dotenv()

@click.group()
def cli() -> None:
    """AgentCore Orchestrator CLI."""


@cli.command("run")
@click.option("--user-id", required=True, help="Requester user id")
@click.option("--query", required=True, help="User query to execute")
@click.option("--tool-name", default=None, help="Preferred tool name")
@click.option("--category", default=None, help="Approval category override")
@click.option("--resource", default=None, help="Target resource identifier")
@click.option("--amount", type=float, default=None, help="Numeric threshold/amount")
@click.option("--environment", default=None, help="Environment")
def run_cmd(user_id: str, query: str, tool_name: Optional[str], category: Optional[str], resource: Optional[str], amount: Optional[float], environment: Optional[str]) -> None:
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
        click.echo(json.dumps(result.model_dump(), indent=2))

    asyncio.run(_run())


if __name__ == "__main__":
    cli()


