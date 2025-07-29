"""
CLI interface for the AgentCore HITL MCP server.

This provides commands to start, configure, and manage the HITL approval server.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional

import click
from pydantic import ValidationError

from .mcp_server import ApprovalConfig, HITLServer, main as mcp_main


@click.group()
@click.version_option()
def cli() -> None:
    """AgentCore Human-in-the-Loop MCP Server CLI."""
    pass


@cli.command()
@click.option(
    "--lambda-url",
    envvar="LAMBDA_FUNCTION_URL",
    required=True,
    help="URL of the approval Lambda function"
)
@click.option(
    "--approver",
    envvar="DEFAULT_APPROVER", 
    default="admin",
    help="Default approver ID"
)
@click.option(
    "--timeout",
    envvar="APPROVAL_TIMEOUT",
    default=1800,
    type=int,
    help="Default timeout for approvals in seconds"
)
@click.option(
    "--auto-approve-low-risk/--no-auto-approve-low-risk",
    envvar="AUTO_APPROVE_LOW_RISK",
    default=True,
    help="Auto-approve low-risk operations"
)
@click.option(
    "--config-file",
    type=click.Path(exists=True),
    help="Path to JSON configuration file"
)
@click.option(
    "--debug/--no-debug",
    default=False,
    help="Enable debug logging"
)
def serve(
    lambda_url: str,
    approver: str,
    timeout: int,
    auto_approve_low_risk: bool,
    config_file: Optional[str],
    debug: bool
) -> None:
    """Start the HITL MCP server."""
    
    # Setup logging
    import logging
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        # Load configuration
        if config_file:
            config = _load_config_from_file(config_file)
        else:
            config = ApprovalConfig(
                lambda_function_url=lambda_url,
                default_approver=approver,
                timeout_seconds=timeout,
                auto_approve_low_risk=auto_approve_low_risk
            )
        
        # Validate configuration
        _validate_config(config)
        
        click.echo(f"Starting HITL MCP server...")
        click.echo(f"Lambda URL: {config.lambda_function_url}")
        click.echo(f"Default approver: {config.default_approver}")
        click.echo(f"Timeout: {config.timeout_seconds}s")
        click.echo(f"Auto-approve low risk: {config.auto_approve_low_risk}")
        
        # Start server
        asyncio.run(_run_server(config))
        
    except ValidationError as e:
        click.echo(f"❌ Configuration error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Error starting server: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="mcp-hitl-config.json",
    help="Output file for MCP configuration"
)
@click.option(
    "--lambda-url",
    envvar="LAMBDA_FUNCTION_URL",
    required=True,
    help="URL of the approval Lambda function"
)
@click.option(
    "--table-name",
    envvar="TABLE_NAME",
    help="DynamoDB table name"
)
@click.option(
    "--sns-topic-arn",
    envvar="SNS_TOPIC_ARN", 
    help="SNS topic ARN"
)
@click.option(
    "--aws-region",
    envvar="AWS_REGION",
    default="us-east-1",
    help="AWS region"
)
def generate_config(
    output: str,
    lambda_url: str,
    table_name: Optional[str],
    sns_topic_arn: Optional[str],
    aws_region: str
) -> None:
    """Generate MCP configuration file."""
    
    config = {
        "mcpServers": {
            "hitl-approval": {
                "command": "uv",
                "args": ["run", "python", "-m", "src.mcp_server"],
                "cwd": ".",
                "env": {
                    "LAMBDA_FUNCTION_URL": lambda_url,
                    "DEFAULT_APPROVER": "${DEFAULT_APPROVER:-admin}",
                    "APPROVAL_TIMEOUT": "${APPROVAL_TIMEOUT:-1800}",
                    "AUTO_APPROVE_LOW_RISK": "${AUTO_APPROVE_LOW_RISK:-true}",
                    "AWS_REGION": aws_region
                }
            }
        }
    }
    
    # Add optional environment variables
    if table_name:
        config["mcpServers"]["hitl-approval"]["env"]["TABLE_NAME"] = table_name
    if sns_topic_arn:
        config["mcpServers"]["hitl-approval"]["env"]["SNS_TOPIC_ARN"] = sns_topic_arn
    
    # Write configuration file
    output_path = Path(output)
    with output_path.open("w") as f:
        json.dump(config, f, indent=2)
    
    click.echo(f"✅ MCP configuration written to {output_path}")
    click.echo("\nTo use this configuration:")
    click.echo("1. Copy the generated config to your MCP client configuration")
    click.echo("2. Set the required environment variables")
    click.echo("3. Restart your MCP client")


@cli.command()
@click.option(
    "--lambda-url",
    envvar="LAMBDA_FUNCTION_URL",
    required=True,
    help="URL of the approval Lambda function"
)
@click.option(
    "--request-id",
    required=True,
    help="Request ID to check"
)
def check_approval(lambda_url: str, request_id: str) -> None:
    """Check the status of an approval request."""
    
    import httpx
    
    try:
        # Make request to Lambda function
        with httpx.Client() as client:
            response = client.get(
                f"{lambda_url}?request_id={request_id}",
                timeout=30.0
            )
            response.raise_for_status()
            
            data = response.json()
            status = data.get("status", "unknown")
            
            status_emoji = {
                "pending": "⏳",
                "approve": "✅",
                "reject": "❌"
            }.get(status, "❓")
            
            click.echo(f"{status_emoji} Request {request_id}: {status}")
            
            if "timestamp" in data:
                click.echo(f"Timestamp: {data['timestamp']}")
            if "approver" in data and data["approver"]:
                click.echo(f"Approver: {data['approver']}")
                
    except httpx.HTTPError as e:
        click.echo(f"❌ HTTP error checking approval: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Error checking approval: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="hitl-config.json",
    help="Output file for server configuration"
)
def init_config(output: str) -> None:
    """Initialize a configuration file with defaults."""
    
    config = {
        "lambda_function_url": "${LAMBDA_FUNCTION_URL}",
        "default_approver": "admin",
        "timeout_seconds": 1800,
        "auto_approve_low_risk": True,
        "required_approvers": {
            "critical_operations": ["admin", "security_team"],
            "database_operations": ["dba", "admin"],
            "system_operations": ["sysadmin", "admin"]
        }
    }
    
    output_path = Path(output)
    with output_path.open("w") as f:
        json.dump(config, f, indent=2)
    
    click.echo(f"✅ Configuration template written to {output_path}")
    click.echo("\nEdit the configuration file and set the required values:")
    click.echo("- lambda_function_url: Your approval Lambda function URL")
    click.echo("- default_approver: Default approver ID")
    click.echo("- required_approvers: Mapping of operation types to required approvers")


def _load_config_from_file(config_file: str) -> ApprovalConfig:
    """Load configuration from JSON file."""
    
    config_path = Path(config_file)
    if not config_path.exists():
        raise click.ClickException(f"Configuration file not found: {config_file}")
    
    try:
        with config_path.open() as f:
            config_data = json.load(f)
        
        # Expand environment variables
        config_data = _expand_env_vars(config_data)
        
        return ApprovalConfig(**config_data)
        
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid JSON in configuration file: {e}")
    except ValidationError as e:
        raise click.ClickException(f"Invalid configuration: {e}")


def _expand_env_vars(data: Dict) -> Dict:
    """Expand environment variables in configuration data."""
    
    def expand_value(value):
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            # Extract variable name and default value
            var_expr = value[2:-1]  # Remove ${ and }
            if ":-" in var_expr:
                var_name, default_value = var_expr.split(":-", 1)
                return os.environ.get(var_name, default_value)
            else:
                return os.environ.get(var_expr, value)
        elif isinstance(value, dict):
            return {k: expand_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [expand_value(item) for item in value]
        else:
            return value
    
    return expand_value(data)


def _validate_config(config: ApprovalConfig) -> None:
    """Validate the configuration."""
    
    if not config.lambda_function_url:
        raise ValidationError("lambda_function_url is required")
    
    if not config.lambda_function_url.startswith(("http://", "https://")):
        raise ValidationError("lambda_function_url must be a valid URL")


async def _run_server(config: ApprovalConfig) -> None:
    """Run the HITL MCP server with the given configuration."""
    
    server = HITLServer(config)
    await server.serve()


if __name__ == "__main__":
    cli() 