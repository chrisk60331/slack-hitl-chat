"""Docstrings are good mkay?"""

import asyncio
import json
import logging
import os
import random
import shutil
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import AsyncExitStack
from typing import Any

import boto3
from botocore import exceptions as botocore_exceptions
from botocore.config import Config as BotoConfig
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config_store import MCPServer, get_mcp_servers

# load_dotenv()  # load environment variables from .env
MAX_ITERATIONS = 20  # Increased limit for complex operations
MAX_TOKENS = 4095
# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)


# System instructions to guide tool usage, especially AWS role add/remove
SYSTEM_PROMPT_PATH: str = os.path.join(
    os.path.dirname(__file__), "system_prompt.txt"
)
try:
    with open(SYSTEM_PROMPT_PATH, encoding="utf-8") as _f:
        SYSTEM_PROMPT: str = _f.read()

except FileNotFoundError:
    # Fallback to an empty prompt if the file is missing to avoid crashes
    SYSTEM_PROMPT = ""
    raise ValueError("SYSTEM_PROMPT_PATH not found")


async def invoke_mcp_client(query: str, requester_email: str = None, allowed_tools: list[str] = None) -> str:
    client = MCPClient()
    try:
        alias_to_path: dict[str, str] = {}
        servers_cfg_list: list[MCPServer] | None = None
        # Prefer config DB MCP servers
        try:
            servers_cfg = get_mcp_servers().servers
            servers_cfg_list = servers_cfg
            disabled_map: dict[str, list[str]] = {}
            for s in servers_cfg:
                if s.enabled:
                    if s.path:
                        alias_to_path[s.alias] = s.path
                    if getattr(s, "disabled_tools", None):
                        disabled_map[s.alias] = list(s.disabled_tools)
            if allowed_tools:
                client.allowed_tools_fq = set(allowed_tools)
            if disabled_map:
                client.set_disabled_tools_map(disabled_map)
        except Exception as e:
            logging.error(f"Error getting MCP servers: {e}")

        if servers_cfg_list:
            await client.connect_to_servers(
                alias_to_path if alias_to_path else None,
                requester_email,
                servers_cfg=servers_cfg_list,
                allowed_tools=allowed_tools,
            )

        response_text = await client.process_query(query, requester_email, allowed_tools)
    finally:
        await client.cleanup()

    return response_text


class MCPClient:
    """MCP Client for connecting to MCP servers and processing queries
    using Claude on Bedrock.
    """

    def __init__(self) -> None:
        """Initialize the MCP client with session and AWS Bedrock client."""
        # Initialize session and client objects
        self.session: ClientSession | None = None
        self.exit_stack = AsyncExitStack()
        # Configure boto3 client with adaptive retries and a larger
        # connection pool
        aws_region = os.environ["AWS_REGION"]
        boto_config = BotoConfig(
            retries={"max_attempts": 10, "mode": "adaptive"},
            max_pool_connections=50,
            connect_timeout=5,
            read_timeout=120,
        )
        self.bedrock = boto3.client(
            "bedrock-runtime", region_name=aws_region, config=boto_config
        )
        # Multi-server support
        self.sessions: dict[str, ClientSession] = {}
        self.tool_registry: dict[str, tuple[str, str]] = {}
        # Per-alias set of disabled tool short-names (no alias prefix)
        self.disabled_tools_by_alias: dict[str, set[str]] = {}
    

    def set_disabled_tools_map(
        self, mapping: dict[str, list[str]] | dict[str, set[str]]
    ) -> None:
        """Set per-alias disabled tool names.

        Args:
            mapping: Dict of alias -> iterable of tool short-names to disable.
        """
        normalized: dict[str, set[str]] = {}
        for alias, names in mapping.items():
            disabled_set = set(names)
            # Normalize to bare short names (defensive if fully-qualified used)
            normalized[alias] = {n.split("__", 1)[-1] for n in disabled_set}
        self.disabled_tools_by_alias = normalized

    def is_tool_allowed(self, alias: str, short_name: str, allowed_tools: list[str]) -> bool:
        """Return True if the tool is not disabled for the given alias."""
        disabled = self.disabled_tools_by_alias.get(alias, set())
        if "Any" in allowed_tools:
            logging.info(f"Tool {short_name} is allowed for alias {alias} and allowed tools: {allowed_tools}")
            return True
        if short_name in disabled:
            logging.info(f"Tool {short_name} is disabled for alias {alias}")
            return False
        if f"{alias}__{short_name}" not in allowed_tools:
            logging.info(f"Tool {short_name} is not allowed for alias {alias} and allowed tools: {allowed_tools}")
            return False
        return True

    def _is_retryable_bedrock_error(self, exc: Exception) -> bool:
        """Return True if the exception is a transient/retryable Bedrock
        error.
        """
        # Network and timeout issues
        if isinstance(
            exc,
            botocore_exceptions.ReadTimeoutError
            | botocore_exceptions.ConnectTimeoutError
            | botocore_exceptions.EndpointConnectionError,
        ):
            return True
        # API-level errors
        if isinstance(exc, botocore_exceptions.ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            return code in {
                "ServiceUnavailableException",
                "ThrottlingException",
                "ModelNotReadyException",
                "TooManyRequestsException",
            }
        # Some SDKs raise specific generated classes that subclass
        # ClientError; detect by name
        name = exc.__class__.__name__
        if name in {
            "ServiceUnavailableException",
            "ThrottlingException",
            "ModelNotReadyException",
        }:
            return True
        return False

    def _invoke_with_retries(
        self,
        *,
        model_id: str,
        body: dict[str, Any],
        max_retries: int = 6,
        base_delay_seconds: float = 0.5,
    ) -> dict[str, Any]:
        """Call Bedrock invoke_model with exponential backoff and jitter.

        Retries on transient Bedrock errors such as service unavailability,
        throttling, model not ready, and network/timeout issues.

        Args:
            model_id: Bedrock model identifier.
            body: Request body to serialize as JSON.
            max_retries: Maximum number of retry attempts on transient failures.
            base_delay_seconds: Initial backoff delay; doubled each retry with jitter.

        Returns:
            Raw response dict from boto3 (includes a 'body' stream).
        """
        attempt = 0
        while True:
            try:
                return self.bedrock.invoke_model(
                    modelId=model_id, body=json.dumps(body)
                )
            except Exception as exc:  # noqa: BLE001 - filtered by helper
                if (
                    not self._is_retryable_bedrock_error(exc)
                    or attempt >= max_retries
                ):
                    logger.error(
                        "bedrock.invoke_model.failed",
                        extra={"attempt": attempt, "error": str(exc)},
                    )
                    raise
                delay = (base_delay_seconds * (2**attempt)) + random.uniform(
                    0, 0.25
                )
                logger.warning(
                    "bedrock.invoke_model.retrying",
                    extra={
                        "attempt": attempt + 1,
                        "delay_seconds": round(delay, 3),
                        "error": str(exc),
                    },
                )
                time.sleep(delay)
                attempt += 1

    def _invoke_stream_with_retries(
        self,
        *,
        model_id: str,
        body: dict[str, Any],
        max_retries: int = 6,
        base_delay_seconds: float = 0.5,
    ) -> dict[str, Any]:
        """Call Bedrock invoke_model_with_response_stream with retry/backoff.

        Args:
            model_id: Bedrock model identifier.
            body: Request body to serialize as JSON.
            max_retries: Maximum number of retry attempts on transient failures.
            base_delay_seconds: Initial backoff delay; doubled each retry with jitter.

        Returns:
            Raw response dict from boto3 (includes a streaming 'body').
        """
        attempt = 0
        while True:
            try:
                return self.bedrock.invoke_model_with_response_stream(
                    modelId=model_id, body=json.dumps(body)
                )
            except Exception as exc:  # noqa: BLE001
                if (
                    not self._is_retryable_bedrock_error(exc)
                    or attempt >= max_retries
                ):
                    logger.error(
                        "bedrock.invoke_model_stream.failed",
                        extra={"attempt": attempt, "error": str(exc)},
                    )
                    raise
                delay = (base_delay_seconds * (2**attempt)) + random.uniform(
                    0, 0.25
                )
                logger.warning(
                    "bedrock.invoke_model_stream.retrying",
                    extra={
                        "attempt": attempt + 1,
                        "delay_seconds": round(delay, 3),
                        "error": str(exc),
                    },
                )
                time.sleep(delay)
                attempt += 1

    async def connect_to_server(self, server_script_path: str) -> None:
        """Connect to an MCP server.

        Args:
            server_script_path: Path to the server script (.py or .js)

        Raises:
            ValueError: If server script is not a .py or .js file
        """
        is_python = server_script_path.endswith(".py")
        is_js = server_script_path.endswith(".js")
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")

        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command, args=[server_script_path], env=None
        )

        logger.info(
            "mcp.connect.begin",
            extra={"command": command, "script": server_script_path},
        )
        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )

        await self.session.initialize()

        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        tool_names = [tool.name for tool in tools]
        logger.info("mcp.connect.done", extra={"tools": ",".join(tool_names)})

    @staticmethod
    def _parse_servers_env(servers_env: str) -> dict[str, str]:
        """Parse MCP_SERVERS env var into a mapping {alias: path}.

        Supports separators "=" or ":" between alias and path, and ";"
        between entries.
        """
        mapping: dict[str, str] = {}
        for part in (servers_env or "").split(";"):
            part = part.strip()
            if not part:
                continue
            sep = "=" if "=" in part else (":" if ":" in part else None)
            if not sep:
                continue
            alias, path = part.split(sep, 1)
            mapping[alias.strip()] = os.path.expanduser(path.strip())
        return mapping

    async def connect_to_servers(
        self,
        alias_to_path: dict[str, str] | None = None,
        requester_email: str | None = None,
        servers_cfg: list[MCPServer] | None = None,
        allowed_tools: list[str] | None = None,
    ) -> None:
        """Connect to multiple MCP servers and build a qualified tool registry.

        Args:
            alias_to_path: Mapping from alias (e.g., "google", "jira") to server script path
        """
        # Build a normalized list of launch specs
        launch_items: list[tuple[str, str, list[str], dict[str, str]]] = []
        if servers_cfg is not None:
            for s in servers_cfg:
                if not s.enabled:
                    continue
                if s.command:
                    cmd = s.command
                    args = list(s.args or [])
                    if requester_email:
                        args = args + [requester_email]

                    env = dict(s.env or {})

                    # If running via uvx in AWS Lambda, default cache dirs to /tmp
                    if cmd == "uvx":
                        # Ensure all uv cache/data/tool dirs point to writable /tmp on Lambda
                        env.setdefault("UV_CACHE_DIR", "/tmp/uvcache")
                        env.setdefault("XDG_CACHE_HOME", "/tmp")
                        env.setdefault("XDG_DATA_HOME", "/tmp")
                        env.setdefault("UV_TOOL_DIR", "/tmp/uvtools")
                    # If running Node-based MCPs via npx/npm/node in Lambda, use /tmp caches
                    if cmd in {"npx", "npm", "node"}:
                        env.setdefault("NPM_CONFIG_CACHE", "/tmp/.npm")
                        env.setdefault("NPX_CACHE_DIR", "/tmp/.npx")
                        # Some tools respect HOME for cache locations
                        env.setdefault("HOME", "/tmp")
                        # Ensure PATH includes /usr/local/bin for Lambda runtime
                        path_val = env.get("PATH") or os.environ.get("PATH", "")
                        if "/usr/local/bin" not in (path_val or "").split(":"):
                            env["PATH"] = (f"/usr/local/bin:{path_val}" if path_val else "/usr/local/bin")

                    # Merge with parent environment so we don't lose PATH/AWS vars
                    merged_env = os.environ.copy()
                    merged_env.update(env)
                    # Prefer npm exec on AWS Lambda to avoid npx wrapper permission issues
                    if cmd == "npx" and os.environ.get("AWS_LAMBDA_RUNTIME_API"):
                        npm_path = shutil.which("npm") or "/usr/local/bin/npm"
                        cmd = npm_path
                        args = ["exec", "-y"] + args
                    launch_items.append((s.alias, cmd, args, merged_env))
                elif s.path:
                    server_script_path = os.path.expanduser(s.path)
                    is_python = server_script_path.endswith(".py")
                    is_js = server_script_path.endswith(".js")
                    if not (is_python or is_js):
                        raise ValueError(
                            f"Server script must be a .py or .js file for alias {s.alias}"
                        )
                    command = "python" if is_python else "node"
                    args = [server_script_path]
                    if requester_email:
                        args.append(requester_email)
                    launch_items.append((s.alias, command, args, {}))
                else:
                    raise ValueError(
                        f"MCP server '{s.alias}' must specify either command or path"
                    )
        elif alias_to_path is not None:
            for alias, server_script_path in alias_to_path.items():
                server_script_path = os.path.expanduser(server_script_path)
                is_python = server_script_path.endswith(".py")
                is_js = server_script_path.endswith(".js")
                if not (is_python or is_js):
                    raise ValueError(
                        f"Server script must be a .py or .js file for alias {alias}"
                    )
                command = "python" if is_python else "node"
                args = [server_script_path]
                if requester_email:
                    args.append(requester_email)
                launch_items.append((alias, command, args, {}))

        for alias, command, args, env in launch_items:
            # Resolve command to absolute path if available (helps in Lambda where PATH may differ)
            resolved = shutil.which(command) or command
            logger.error(
                f"Connecting to server {resolved} {args} with requester email {requester_email}"
            )

            server_params = StdioServerParameters(
                command=resolved,
                args=args,
                env=env or None,
            )
            logger.info(
                "mcp.connect.begin",
                extra={
                    "alias": alias,
                    "command": resolved,
                    "script": " ".join(args),
                },
            )

            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )

            stdio, write = stdio_transport
            session = await self.exit_stack.enter_async_context(
                ClientSession(stdio, write)
            )
            try:
                await session.initialize()
            except:
                server_params = StdioServerParameters(
                    command=resolved,
                    args=[args[0]],
                    env=env or None,
                    allowed_tools=allowed_tools,
                )
                stdio_transport = await self.exit_stack.enter_async_context(
                    stdio_client(server_params)
                )

                stdio, write = stdio_transport
                session = await self.exit_stack.enter_async_context(
                    ClientSession(stdio, write)
                )
                await session.initialize()
            self.sessions[alias] = session

            response = await session.list_tools()
            for tool in response.tools:
                qualified_name = f"{alias}__{tool.name}"
                if qualified_name not in allowed_tools:
                    continue
                self.tool_registry[qualified_name] = (alias, tool.name)
            logger.info(
                "mcp.connect.done",
                extra={"alias": alias, "tool_count": len(response.tools)},
            )

    async def process_query(
        self, query: str, requester_email: str = None, allowed_tools: list[str] = None
    ) -> str:
        """Process a query using Claude on Bedrock and available tools.

        Args:
            query: The natural language query to process

        Returns:
            The response from Claude after potentially calling tools
        """
        logger.info("mcp.process_query", extra={"query_preview": query[:200]})
        # Auto-connect to multiple servers if configured and none connected
        if self.session is None and not self.sessions:
            servers_env = os.getenv("MCP_SERVERS", "").strip()
            if servers_env:
                mapping = self._parse_servers_env(servers_env)
                if mapping:
                    await self.connect_to_servers(mapping, requester_email)
        messages = [
            {"role": "user", "content": [{"type": "text", "text": query}]}
        ]

        # Discover tools from either single session or multi-sessions
        available_tools: list[dict[str, Any]] = []
        if self.sessions:
            logger.error(f"Allowed tools: {allowed_tools}")
            for _qualified, (_alias, _tname) in self.tool_registry.items():
                # We cannot fetch input schema here without another call; rely on list_tools per session
                # Build available tools by querying each session once
                pass
            # Query each session and add qualified tools
            for alias, session in self.sessions.items():
                tools_resp = await session.list_tools()
                for tool in tools_resp.tools:
                    short_name = tool.name
                    if not self.is_tool_allowed(alias, short_name, allowed_tools):
                        continue
                    available_tools.append(
                        {
                            "name": f"{alias}__{short_name}",
                            "description": tool.description,
                            "input_schema": tool.inputSchema,
                        }
                    )
        else:
            logger.info(f"Allowed tools: {allowed_tools}")
            response = await self.session.list_tools()
            available_tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                }
                for tool in response.tools
                if tool.name in allowed_tools
            ]

        iteration = 0
        logger.info(f"Available tools: {available_tools}")
        while iteration < MAX_ITERATIONS:
            iteration += 1
            logger.info(
                f"Starting conversation iteration {iteration}/{MAX_ITERATIONS}"
            )
            if not available_tools:
                assistant_content = "No tools available to call. You wont be able to complete the task."
                messages.append(
                    {"role": "assistant", "content": assistant_content},
                )


            # Prepare request body for Bedrock
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": MAX_TOKENS,  # Increased token limit
                "messages": messages,
                "tools": available_tools,
                "system": SYSTEM_PROMPT,
            }

            # Claude API call via Bedrock
            logger.info(
                f"Calling Claude with {len(messages)} messages and {len(available_tools)} tools"
            )
            response = self._invoke_with_retries(
                model_id=os.environ.get("BEDROCK_MODEL_ID"),
                body=request_body,
            )

            response_body = json.loads(response["body"].read())
            assistant_content = response_body.get("content", [])

            # Add assistant response to messages
            messages.append(
                {"role": "assistant", "content": assistant_content}
            )

            # Check if there are any tool calls to process
            tool_calls = [
                content
                for content in assistant_content
                if content.get("type") == "tool_use"
            ]
            logger.debug("mcp.tool_calls", extra={"count": len(tool_calls)})

            if not tool_calls:
                # No tool calls, extract and return the final response
                final_text = []
                for content in assistant_content:
                    if content.get("type") == "text":
                        final_text.append(content.get("text", ""))
                result = "\n".join(final_text).strip()
                logger.info(
                    f"Conversation completed in {iteration} iterations"
                )
                # Return non-empty result or a success message
                return result if result else "Task completed successfully."

            # Execute all tool calls and prepare tool results
            tool_results = []
            for tool_content in tool_calls:
                tool_name = tool_content.get("name")
                tool_args = tool_content.get("input", {})
                tool_use_id = tool_content.get("id")

                try:
                    logger.error(f"mcp.tool.execute extra={tool_name}")
                    # Execute tool call
                    if self.sessions and "__" in tool_name:
                        alias, short_name = tool_name.split("__", 1)
                        target_session = self.sessions.get(alias)
                        if target_session is None:
                            raise ValueError(
                                f"No MCP session for alias {alias}"
                            )
                        if not self.is_tool_allowed(alias, short_name, allowed_tools):
                            raise ValueError(
                                f"Tool '{short_name}' is disabled for alias '{alias}'"
                            )
                        result = await target_session.call_tool(
                            short_name, tool_args
                        )
                    else:
                        result = await self.session.call_tool(
                            tool_name, tool_args
                        )

                    tool_output = str(result.content)

                    logger.error(f"Tool {tool_name} output: {tool_output}")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": tool_output,
                        }
                    )
                    logger.info(f"Tool {tool_name} executed successfully")
                except Exception as e:
                    logger.error(f"Error executing tool {tool_name}: {str(e)}")
                    # Handle tool execution errors
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": f"Error executing tool {tool_name}: {str(e)}",
                            "is_error": True,
                        }
                    )

            # Add user message with all tool results
            logger.debug(
                f"Adding {len(tool_results)} tool results to conversation"
            )
            messages.append({"role": "user", "content": tool_results})

        # If we reach here, we hit max iterations
        return f"Task partially completed but reached maximum conversation iterations ({MAX_ITERATIONS}). The assistant may need simpler instructions or the task may be too complex for automated execution."

    def stream_text(self, query: str) -> Iterator[str]:
        """Stream tokens from Bedrock (Anthropic Messages) in real time.

        This method uses invoke_model_with_response_stream to yield token deltas
        from Claude. It does not perform MCP tool calls; it's intended for
        lightweight, low-latency streaming to UIs (e.g., Slack SSE).

        Args:
            query: The natural language prompt to send to the model.

        Yields:
            Token text chunks (may be partial words).
        """
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": MAX_TOKENS,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": query}]}
            ],
            "system": SYSTEM_PROMPT,
        }

        response = self._invoke_stream_with_retries(
            model_id=os.environ.get("BEDROCK_MODEL_ID"),
            body=request_body,
        )

        # The streaming body yields events; `chunk` contains the JSON lines
        stream = response.get("body")
        if stream is None:
            return
        for event in stream:
            chunk = event.get("chunk")
            if not chunk:
                continue
            data = chunk.get("bytes")
            if not data:
                continue
            try:
                payload = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            # Anthropic streaming events: we care about contentBlockDelta for token text
            if payload.get("type") == "contentBlockDelta":
                delta = payload.get("delta") or {}
                text = delta.get("text")
                if text:
                    yield text

    async def stream_conversation(
        self, query: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a full conversation with tool use events and token deltas.

        Yields structured events:
          - {"type": "token", "text": str}
          - {"type": "tool_call", "name": str, "args": dict}
          - {"type": "tool_result", "name": str, "content": str}
          - {"type": "final", "text": str}
          - {"type": "error", "message": str}

        This processes model turns in a loop. On each turn it streams text tokens
        while also detecting tool_use blocks. After the turn completes, any
        detected tool calls are executed via MCP and appended as tool_result
        content to the next request messages, continuing until no more tools are
        requested. Finally emits a "final" event.
        """
        import uuid

        if self.session is None and not self.sessions:
            # Auto-connect if configured via MCP_SERVERS
            servers_env = os.getenv("MCP_SERVERS", "").strip()
            if servers_env:
                mapping = self._parse_servers_env(servers_env)
                if mapping:
                    await self.connect_to_servers(mapping)
            if self.session is None and not self.sessions:
                # If caller forgot to connect, provide a clear error
                yield {
                    "type": "error",
                    "message": "MCP session not initialized",
                }
                return

        # Discover tools from MCP server
        # Build tools list (single or multi-session)
        available_tools: list[dict[str, Any]] = []
        if self.sessions:
            for alias, session in self.sessions.items():
                tools_resp = await session.list_tools()  # type: ignore[func-returns-value]
                for t in tools_resp.tools:
                    short_name = t.name
                    if not self.is_tool_allowed(alias, short_name):
                        continue
                    available_tools.append(
                        {
                            "name": f"{alias}__{short_name}",
                            "description": t.description,
                            "input_schema": t.inputSchema,
                        }
                    )
        else:
            tools_resp = await self.session.list_tools()  # type: ignore[func-returns-value]
            available_tools = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.inputSchema,
                }
                for t in tools_resp.tools
            ]

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": [{"type": "text", "text": query}]}
        ]

        # Loop until no more tool calls
        for _iter in range(MAX_ITERATIONS):
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": MAX_TOKENS,
                "messages": messages,
                "tools": available_tools,
                "system": SYSTEM_PROMPT,
            }

            # State for this streamed message
            assistant_text_parts: list[str] = []
            pending_tool_calls: list[dict[str, Any]] = []
            current_block_type: str | None = None
            current_tool_name: str | None = None
            current_tool_id: str | None = None
            tool_input_buffer: list[str] = []

            response = self._invoke_stream_with_retries(
                model_id=os.environ.get("BEDROCK_MODEL_ID"),
                body=request_body,
            )
            stream = response.get("body")
            if stream is None:
                yield {"type": "error", "message": "no stream body"}
                break

            for event in stream:
                chunk = event.get("chunk")
                if not chunk:
                    continue
                data = chunk.get("bytes")
                if not data:
                    continue
                try:
                    payload = json.loads(data.decode("utf-8"))
                except Exception:
                    continue

                ptype = payload.get("type")
                if ptype == "contentBlockStart":
                    block = payload.get("contentBlock", {})
                    current_block_type = block.get("type")
                    if current_block_type == "tool_use":
                        current_tool_name = block.get("name")
                        current_tool_id = (
                            block.get("id") or f"tool-{uuid.uuid4().hex[:8]}"
                        )
                        tool_input_buffer = []
                elif ptype == "contentBlockDelta":
                    delta = payload.get("delta", {})
                    # Text streaming
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            assistant_text_parts.append(text)
                            yield {"type": "token", "text": text}
                    # Tool input JSON streaming
                    if delta.get("type") == "input_json_delta":
                        partial = delta.get("partial_json", "")
                        if partial:
                            tool_input_buffer.append(partial)
                elif ptype == "contentBlockStop":
                    if current_block_type == "tool_use":
                        # Finalize tool input JSON
                        args_json = (
                            "".join(tool_input_buffer) or "{}"
                        ).strip()
                        try:
                            tool_args = json.loads(args_json)
                        except Exception:
                            tool_args = {"_raw": args_json}
                        if current_tool_name:
                            pending_tool_calls.append(
                                {
                                    "name": current_tool_name,
                                    "id": current_tool_id,
                                    "args": tool_args,
                                }
                            )
                    current_block_type = None
                    current_tool_name = None
                    current_tool_id = None
                    tool_input_buffer = []
                elif ptype == "messageStop":
                    # End of this assistant turn
                    break

            # If there are tool calls, execute them and continue loop
            if pending_tool_calls:
                print(f"Pending tool calls: {pending_tool_calls}")
                tool_results_content: list[dict[str, Any]] = []
                for call in pending_tool_calls:
                    yield {
                        "type": "tool_call",
                        "name": call["name"],
                        "args": call["args"],
                    }
                    try:
                        # Execute via MCP (dispatch by alias if needed)
                        if self.sessions and "__" in call["name"]:
                            alias, short_name = call["name"].split("__", 1)
                            target_session = self.sessions.get(alias)
                            if target_session is None:
                                print(f"No MCP session for alias {alias}")
                                raise ValueError(
                                    f"No MCP session for alias {alias}"
                                )
                            print(f"Calling session tool {short_name} with args {call['args']}")
                            if not self.is_tool_allowed(alias, short_name):
                                raise ValueError(
                                    f"Tool '{short_name}' is not allowed for alias '{alias}'"
                                )
                            result = await target_session.call_tool(
                                short_name, call["args"]
                            )  # type: ignore[func-returns-value]
                        else:
                            # When only a single session exists, the model may emit bare names.
                            # If an allowlist is configured, reject bare names not present in it.
                            print(f"Calling tool {call['name']} with args {call['args']}")
                            result = await self.session.call_tool(call["name"], call["args"])  # type: ignore[func-returns-value]
                        content_str = str(result.content)
                        yield {
                            "type": "tool_result",
                            "name": call["name"],
                            "content": content_str,
                        }
                        tool_results_content.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": call.get("id") or "",
                                "content": content_str,
                            }
                        )
                    except Exception as e:  # pragma: no cover - defensive
                        err = f"Error executing tool {call['name']}: {e}"
                        yield {
                            "type": "tool_result",
                            "name": call["name"],
                            "content": err,
                            "is_error": True,
                        }
                        tool_results_content.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": call.get("id") or "",
                                "content": err,
                                "is_error": True,
                            }
                        )

                # Add tool results as a user message and continue
                messages.append(
                    {"role": "user", "content": tool_results_content}
                )
                continue

            # No tools requested; finalize
            final_text = "".join(assistant_text_parts).strip()
            yield {"type": "final", "text": final_text}
            break

    async def chat_loop(self) -> None:
        """Run an interactive chat loop."""
        while True:
            try:
                query = input("\nQuery: ").strip()

                if query.lower() == "quit":
                    break

                response = await self.process_query(query)

            except Exception as e:
                logging.error(f"\nError: {str(e)}")

    async def cleanup(self) -> None:
        """Clean up resources."""
        await self.exit_stack.aclose()


async def main() -> None:
    """Main function for running the MCP client from command line."""
    if len(sys.argv) < 2:
        print("Usage: python client.py <path_to_server_script>")
        sys.exit(1)

    client = MCPClient()
    try:
        await client.connect_to_server(sys.argv[1])
        await client.process_query(sys.argv[2])
    finally:
        await client.cleanup()


if __name__ == "__main__":
    import sys

    asyncio.run(main())
