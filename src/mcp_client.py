"""Docstrings are good mkay?"""
import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack
from typing import Dict, List, Any, Optional, Iterator, Iterable, AsyncIterator, Tuple

import boto3
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()  # load environment variables from .env
MAX_ITERATIONS = 20  # Increased limit for complex operations
# Set up logging
logger = logging.getLogger(__name__)
print(f"Logger: {logger}")

# System instructions to guide tool usage, especially AWS role add/remove
SYSTEM_PROMPT: str = (
    "You are an execution agent that must correctly call MCP tools.\n"
    "General rules:\n"
    "- Always pass tool inputs under a top-level 'request' object, matching the tool's input schema.\n"
    "- Prefer idempotent behavior: check state first, then add/remove only if needed.\n"
    "- Only claim success if the final tool confirms success; otherwise state the actual outcome (already had role / not found / error).\n\n"
    "AWS role access management:\n"
    "- To GRANT access, call add_amazon_role with fields: user_key, admin_role, identity_provider. Account ID is derived from ARNs.\n"
    "  - admin_role MUST be the FULL AWS role ARN in the form arn:aws:iam::ACCOUNT_ID:role/ROLE_NAME.\n"
    "  - identity_provider defaults to NMDGoogle if not specified.\n"
    "- To REVOKE access, call remove_amazon_role with the same fields.\n"
    "- Parse role ARNs provided in user requests. Example: from 'arn:aws:iam::250623887600:role/NMD-Admin-Scaia'\n"
    "  - example admin_role = arn:aws:iam::123456789012:role/Admin\n"
    "  - admin_role = arn:aws:iam::250623887600:role/NMD-Admin-Scaia\n\n"
    "Idempotency flow:\n"
    "- Before add/remove, call get_amazon_roles to see current assignments for the user.\n"
    "- If the exact role already exists for that account, report 'already has role' and do NOT call add_amazon_role.\n"
    "- If removing and the role is not present, report 'role not found' and do NOT call remove_amazon_role.\n\n"
    "Examples (tool input payloads):\n"
    "- add_amazon_role input: {\"request\":{\"user_key\":\"user@example.com\",\"admin_role\":\"arn:aws:iam::123456789012:role/NMD-Admin\",\"identity_provider\":\"arn:aws:iam::108968357292:saml-provider/NMDGoogle\"}}\n"
    "- remove_amazon_role input: {\"request\":{\"user_key\":\"user@example.com\",\"admin_role\":\"arn:aws:iam::123456789012:role/NMD-Admin\",\"identity_provider\":\"arn:aws:iam::108968357292:saml-provider/NMDGoogle\"}}\n\n"
    "Error correction:\n"
    "- If a tool returns 'Invalid role format' or indicates missing fields, immediately retry with admin_role set to the full ARN and ensure identity_provider is included.\n"
)
class MCPClient:
    """MCP Client for connecting to MCP servers and processing queries using Claude on Bedrock."""
    
    def __init__(self) -> None:
        """Initialize the MCP client with session and AWS Bedrock client."""
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.bedrock = boto3.client('bedrock-runtime', region_name=os.environ['AWS_REGION'])
        # Multi-server support
        self.sessions: Dict[str, ClientSession] = {}
        self.tool_registry: Dict[str, Tuple[str, str]] = {}

    async def connect_to_server(self, server_script_path: str) -> None:
        """Connect to an MCP server.

        Args:
            server_script_path: Path to the server script (.py or .js)
            
        Raises:
            ValueError: If server script is not a .py or .js file
        """
        is_python = server_script_path.endswith('.py')
        is_js = server_script_path.endswith('.js')
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")

        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path],
            env=None
        )

        logger.info("mcp.connect.begin", extra={"command": command, "script": server_script_path})
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

        await self.session.initialize()

        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        tool_names = [tool.name for tool in tools]
        logger.info("mcp.connect.done", extra={"tools": ",".join(tool_names)})

    async def connect_to_servers(self, alias_to_path: Dict[str, str]) -> None:
        """Connect to multiple MCP servers and build a qualified tool registry.

        Args:
            alias_to_path: Mapping from alias (e.g., "google", "jira") to server script path
        """
        print(f"alias_to_path {alias_to_path}")
        alias, server_script_path = alias_to_path.split(":")
        print(f"alias {alias} server_script_path {server_script_path}")
        server_script_path = os.path.expanduser(server_script_path)
        is_python = server_script_path.endswith('.py')
        is_js = server_script_path.endswith('.js')
        if not (is_python or is_js):
            raise ValueError(f"Server script must be a .py or .js file for alias {alias}")

        command = "python" if is_python else "node"
        server_params = StdioServerParameters(command=command, args=[server_script_path], env=None)
        logger.info("mcp.connect.begin", extra={"alias": alias, "command": command, "script": server_script_path})
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        stdio, write = stdio_transport
        session = await self.exit_stack.enter_async_context(ClientSession(stdio, write))
        await session.initialize()
        self.sessions[alias] = session

        response = await session.list_tools()
        for tool in response.tools:
            qualified_name = f"{alias}__{tool.name}"
            self.tool_registry[qualified_name] = (alias, tool.name)
        logger.info("mcp.connect.done", extra={"alias": alias, "tool_count": len(response.tools)})

    async def process_query(self, query: str) -> str:
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
            print(f"servers_env {servers_env}")
            if servers_env:
                alias_to_path: Dict[str, str] = {}
                for part in servers_env.split(";"):
                    if part:
                        await self.connect_to_servers(part)
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": query}] 
            }
        ]

        # Discover tools from either single session or multi-sessions
        available_tools: List[Dict[str, Any]] = []
        if self.sessions:
            for qualified, (_alias, _tname) in self.tool_registry.items():
                # We cannot fetch input schema here without another call; rely on list_tools per session
                # Build available tools by querying each session once
                pass
            # Query each session and add qualified tools
            for alias, session in self.sessions.items():
                tools_resp = await session.list_tools()
                for tool in tools_resp.tools:
                    available_tools.append({
                        "name": f"{alias}__{tool.name}",
                        "description": tool.description,
                        "input_schema": tool.inputSchema,
                    })
        else:
            response = await self.session.list_tools()
            available_tools = [{
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema
            } for tool in response.tools]

        
        iteration = 0
        
        while iteration < MAX_ITERATIONS:
            iteration += 1
            logger.info(f"Starting conversation iteration {iteration}/{MAX_ITERATIONS}")
            
            # Prepare request body for Bedrock
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2000,  # Increased token limit
                "messages": messages,
                "tools": available_tools,
                "system": SYSTEM_PROMPT,
            }

            # Claude API call via Bedrock
            logger.debug(f"Calling Claude with {len(messages)} messages and {len(available_tools)} tools")
            response = self.bedrock.invoke_model(
                modelId="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
                body=json.dumps(request_body)
            )

            response_body = json.loads(response['body'].read())
            assistant_content = response_body.get('content', [])
            
            # Add assistant response to messages
            messages.append({
                "role": "assistant", 
                "content": assistant_content
            })
            
            # Check if there are any tool calls to process
            tool_calls = [content for content in assistant_content if content.get('type') == 'tool_use']
            logger.info("mcp.tool_calls", extra={"count": len(tool_calls)})
            
            if not tool_calls:
                # No tool calls, extract and return the final response
                final_text = []
                for content in assistant_content:
                    if content.get('type') == 'text':
                        final_text.append(content.get('text', ''))
                result = "\n".join(final_text).strip()
                
                logger.info(f"Conversation completed in {iteration} iterations")
                # Return non-empty result or a success message
                return result if result else "Task completed successfully."
            
            # Execute all tool calls and prepare tool results
            tool_results = []
            for tool_content in tool_calls:
                tool_name = tool_content.get('name')
                tool_args = tool_content.get('input', {})
                tool_use_id = tool_content.get('id')

                try:
                    logger.info("mcp.tool.execute", extra={"name": tool_name})
                    # Execute tool call
                    if self.sessions and "__" in tool_name:
                        alias, short_name = tool_name.split("__", 1)
                        target_session = self.sessions.get(alias)
                        if target_session is None:
                            raise ValueError(f"No MCP session for alias {alias}")
                        result = await target_session.call_tool(short_name, tool_args)
                    else:
                        result = await self.session.call_tool(tool_name, tool_args)
                    
                    tool_output = str(result.content)
                    print(f"Tool '{tool_name}' output: {tool_output}")
                    
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": tool_output
                    })
                    logger.info(f"Tool {tool_name} executed successfully")
                except Exception as e:
                    logger.error(f"Error executing tool {tool_name}: {str(e)}")
                    # Handle tool execution errors
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": f"Error executing tool {tool_name}: {str(e)}",
                        "is_error": True
                    })
            
            # Add user message with all tool results
            logger.debug(f"Adding {len(tool_results)} tool results to conversation")
            messages.append({
                "role": "user",
                "content": tool_results
            })
        
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
            "max_tokens": 2000,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": query}]}
            ],
            "system": SYSTEM_PROMPT,
        }

        response = self.bedrock.invoke_model_with_response_stream(
            modelId="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            body=json.dumps(request_body)
        )

        # The streaming body yields events; `chunk` contains the JSON lines
        stream = response.get('body')
        if stream is None:
            return
        for event in stream:
            chunk = event.get('chunk')
            if not chunk:
                continue
            data = chunk.get('bytes')
            if not data:
                continue
            try:
                payload = json.loads(data.decode('utf-8'))
            except Exception:
                continue
            # Anthropic streaming events: we care about contentBlockDelta for token text
            if payload.get('type') == 'contentBlockDelta':
                delta = payload.get('delta') or {}
                text = delta.get('text')
                if text:
                    yield text

    async def stream_conversation(self, query: str) -> AsyncIterator[Dict[str, Any]]:
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
                alias_to_path: Dict[str, str] = {}
                for part in servers_env.split(";"):
                    if not part:
                        continue
                    if "=" not in part:
                        continue
                    alias, path = part.split("=", 1)
                    alias_to_path[alias.strip()] = path.strip()
                if alias_to_path:
                    await self.connect_to_servers(alias_to_path)
            if self.session is None and not self.sessions:
                # If caller forgot to connect, provide a clear error
                yield {"type": "error", "message": "MCP session not initialized"}
                return

        # Discover tools from MCP server
        # Build tools list (single or multi-session)
        available_tools: List[Dict[str, Any]] = []
        if self.sessions:
            for alias, session in self.sessions.items():
                tools_resp = await session.list_tools()  # type: ignore[func-returns-value]
                for t in tools_resp.tools:
                    available_tools.append({
                        "name": f"{alias}__{t.name}",
                        "description": t.description,
                        "input_schema": t.inputSchema,
                    })
        else:
            tools_resp = await self.session.list_tools()  # type: ignore[func-returns-value]
            available_tools = [
                {"name": t.name, "description": t.description, "input_schema": t.inputSchema}
                for t in tools_resp.tools
            ]

        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": [{"type": "text", "text": query}]}
        ]

        # Loop until no more tool calls
        for _iter in range(MAX_ITERATIONS):
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2000,
                "messages": messages,
                "tools": available_tools,
                "system": SYSTEM_PROMPT,
            }

            # State for this streamed message
            assistant_text_parts: List[str] = []
            pending_tool_calls: List[Dict[str, Any]] = []
            current_block_type: Optional[str] = None
            current_tool_name: Optional[str] = None
            current_tool_id: Optional[str] = None
            tool_input_buffer: List[str] = []

            response = self.bedrock.invoke_model_with_response_stream(
                modelId="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
                body=json.dumps(request_body),
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
                        current_tool_id = block.get("id") or f"tool-{uuid.uuid4().hex[:8]}"
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
                        args_json = ("".join(tool_input_buffer) or "{}").strip()
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
                tool_results_content: List[Dict[str, Any]] = []
                for call in pending_tool_calls:
                    yield {"type": "tool_call", "name": call["name"], "args": call["args"]}
                    try:
                        # Execute via MCP (dispatch by alias if needed)
                        if self.sessions and "__" in call["name"]:
                            alias, short_name = call["name"].split("__", 1)
                            target_session = self.sessions.get(alias)
                            if target_session is None:
                                raise ValueError(f"No MCP session for alias {alias}")
                            result = await target_session.call_tool(short_name, call["args"])  # type: ignore[func-returns-value]
                        else:
                            result = await self.session.call_tool(call["name"], call["args"])  # type: ignore[func-returns-value]
                        content_str = str(result.content)
                        yield {"type": "tool_result", "name": call["name"], "content": content_str}
                        tool_results_content.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": call.get("id") or "",
                                "content": content_str,
                            }
                        )
                    except Exception as e:  # pragma: no cover - defensive
                        err = f"Error executing tool {call['name']}: {e}"
                        yield {"type": "tool_result", "name": call["name"], "content": err, "is_error": True}
                        tool_results_content.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": call.get("id") or "",
                                "content": err,
                                "is_error": True,
                            }
                        )

                # Add tool results as a user message and continue
                messages.append({"role": "user", "content": tool_results_content})
                continue

            # No tools requested; finalize
            final_text = "".join(assistant_text_parts).strip()
            yield {"type": "final", "text": final_text}
            break

    async def chat_loop(self) -> None:
        """Run an interactive chat loop."""
        print("\nMCP Client Started!")
        print("Type your queries or 'quit' to exit.")

        while True:
            try:
                query = input("\nQuery: ").strip()

                if query.lower() == 'quit':
                    break

                response = await self.process_query(query)
                print("\n" + response)

            except Exception as e:
                print(f"\nError: {str(e)}")

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


