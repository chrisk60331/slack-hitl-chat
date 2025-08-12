"""Docstrings are good mkay?"""
import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack
from typing import Dict, List, Any, Optional

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

        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

        await self.session.initialize()

        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        print("\nConnected to server with tools:", [tool.name for tool in tools])

    async def process_query(self, query: str) -> str:
        """Process a query using Claude on Bedrock and available tools.
        
        Args:
            query: The natural language query to process
            
        Returns:
            The response from Claude after potentially calling tools
        """
        print(f"Processing query: {query}")
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": query}] 
            }
        ]

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
            print(f"Assistant response contains {len(tool_calls)} tool calls: {tool_calls}")
            
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
                    logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
                    # Execute tool call
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


