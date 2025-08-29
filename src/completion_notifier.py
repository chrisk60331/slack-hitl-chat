"""Completion notifier Lambda.

Posts the final execution result as threaded replies in Slack once the
approved action has completed. This implementation does not update the
original message; it always posts replies in the same thread to avoid
any Slack rendering quirks with ordered lists or rich text blocks.

Inputs (from Step Functions):
- request_id: The approval request id used to look up metadata in DynamoDB
- result: The full Execute Lambda result object (arbitrary shape)

Behavior:
- Look up the approval item by request_id
- If Slack metadata is present (slack_ts, slack_channel), post one or more
  chat.postMessage calls using ``thread_ts`` to reply in-thread. Long outputs
  are paginated; all pages are replies.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from typing import Any
from pprint import pprint

import src.slack_blockkit as slack_blockkit
from src.dynamodb_utils import get_approval_table
MAX_BLOCKS = 50
MAX_SECTION_CHARS = 2900  # safety < 3000
MAX_MESSAGE_CHARS = 3000  # hard per-response character target


def _extract_text_from_result(result_obj: Any) -> str:
    """Return a concise string from an arbitrary result object.

    Args:
        result_obj: Arbitrary object coming from Execute Lambda.

    Returns:
        String to post into Slack.
    """
    # Common shapes:
    # - {'statusCode': 200, 'body': '...'}
    # - dict with 'body' or 'result' keys
    try:
        if isinstance(result_obj, dict):
            # If nested under 'body' and is JSON string or object
            body = result_obj.get("body")
            if isinstance(body, dict | list):
                return json.dumps(body)
            if isinstance(body, str):
                return body
            # Fallback to a generic dump
            return json.dumps(result_obj)
        # If the result is a raw string
        if isinstance(result_obj, str):
            return result_obj
        return json.dumps(result_obj)
    except Exception:
        return str(result_obj)


def _chunk_text(text: str, max_len: int) -> Iterable[str]:
    """Yield sentence-first chunks no longer than max_len.

    Preference is given to smaller, sentence-aligned chunks. Falls back to
    word and then hard slicing when sentences exceed the limit.
    """
    import re

    if max_len <= 0:
        return []

    # Split into rough sentence tokens, treating newlines as boundaries too.
    # Examples of tokens captured: "Hello world.", "How are you?", "\n\n",
    # and trailing text without terminal punctuation.
    sentence_tokens: list[str] = [
        m.group(0)
        for m in re.finditer(r"[^.!?\n]+[.!?]|\n+|[^.!?\n]+$", text)
    ]

    target_len = max(1, int(max_len * 0.75))  # favor smaller chunks
    current_chunk: str = ""

    def flush_current() -> Iterable[str]:
        nonlocal current_chunk
        if current_chunk:
            yield current_chunk.rstrip()
            current_chunk = ""

    for token in sentence_tokens:
        if not token:
            continue

        # If single token is already longer than max_len, break it down.
        if len(token) > max_len:
            # First, flush any existing chunk.
            yield from flush_current()

            # Try word-based splitting, preserving whitespace that follows words.
            for word in re.findall(r"\S+\s*", token):
                if len(word) > max_len:
                    # Hard slice extremely long words/tokens.
                    start = 0
                    while start < len(word):
                        end = min(start + max_len, len(word))
                        yield word[start:end]
                        start = end
                else:
                    if len(word) + len(current_chunk) > max_len:
                        yield from flush_current()
                    current_chunk += word
            continue

        # If adding this token would exceed max_len, flush first.
        if len(current_chunk) + len(token) > max_len:
            yield from flush_current()

        # If we already reached the preferred size, start a new chunk to
        # intentionally keep chunks smaller when possible.
        if len(current_chunk) >= target_len:
            yield from flush_current()

        current_chunk += token

    # Flush any remaining content.
    if current_chunk:
        yield current_chunk.rstrip()


def _build_blocks_from_text(
    text: str, *, request_id: str | None
) -> tuple[list[dict[str, Any]], int]:
    """Craft a Block Kit message from raw or markdown text.

    Structure:
    - Header: "Execution Result"
    - Context: Request ID when available
    - One or more section blocks with mrkdwn text (chunked)
    - If text appears JSON-like, render each section inside ``` fences
    """
    # First, try to parse text as JSON payload from an MCP tool
    try:
        obj = json.loads(text)
    except Exception:
        obj = None

    # If it's a GIF payload or contains explicit blocks, construct the exact
    # structure requested: header, context, rich text sections, then image.
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Execution Result"}},
        {
            "type": "rich_text",
            "elements": [
                {
                    "type": "rich_text_section",
                    "elements": [
                        {"type": "text", "text": "Request ID: "},
                        {"type": "text", "text": str(request_id or ""), "style": {"code": True}},
                    ],
                }
            ],
        },
    ]
    char_count = 0
    for line in text.split("\n"):
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("https://"):
            # Count this as a block
            if len(blocks) >= MAX_BLOCKS:
                break
            blocks.append({"type": "image", "image_url": line, "alt_text": "image"})
        else:
            for part in _chunk_text(line + "\n", MAX_SECTION_CHARS):
                char_count += len(part)
                if len(blocks) >= MAX_BLOCKS:
                    break
                blocks.append(
                    {
                        "type": "rich_text",
                        "elements": [
                            {
                                "type": "rich_text_section",
                                "elements": [
                                    {"type": "text", "text": part},
                                ],
                            }
                        ],
                    }
                )
        if len(blocks) >= MAX_BLOCKS:
            break

    return  blocks, char_count


def _paginate_blocks_for_slack_messages(
    blocks: list[dict[str, Any]], *, max_chars: int = MAX_MESSAGE_CHARS
) -> list[list[dict[str, Any]]]:
    """Split blocks into multiple messages each under max_chars cumulative section text.

    Slack limits mrkdwn text in a section to 3000 chars; we also keep the sum of
    section texts per message under 3000 to respect an overall per-response target.

    The first message retains leading header/context blocks if present; continuation
    messages include only content blocks. The block count per message is capped by
    MAX_BLOCKS.

    Args:
        blocks: Full block set to split (typically header, context, then sections/images)
        max_chars: Maximum total characters across section texts per message

    Returns:
        A list of block lists, each representing a Slack message payload.
    """
    if not blocks:
        return []

    # Detect leading header/context to include only in the first page
    header_context: list[dict[str, Any]] = []
    content_blocks: list[dict[str, Any]] = []
    for idx, blk in enumerate(blocks):
        if idx < 2 and blk.get("type") in {"header", "context"}:
            header_context.append(blk)
        else:
            content_blocks.append(blk)

    # Fast path: if total section chars already under max and blocks count small
    def _rich_text_len(b: dict[str, Any]) -> int:
        if b.get("type") == "rich_text":
            try:
                total = 0
                for el in b.get("elements") or []:
                    if (el or {}).get("type") == "rich_text_section":
                        for seg in (el.get("elements") or []):
                            if (seg or {}).get("type") == "text":
                                total += len(seg.get("text") or "")
                    elif (el or {}).get("type") == "rich_text_preformatted":
                        for seg in (el.get("elements") or []):
                            if (seg or {}).get("type") == "text":
                                total += len(seg.get("text") or "")
                return total
            except Exception:
                return 0
        if b.get("type") == "section":
            try:
                return len(((b.get("text") or {}).get("text")) or "")
            except Exception:
                return 0
        return 0

    total_section_chars = 0
    for b in content_blocks:
        total_section_chars += _rich_text_len(b)
    if total_section_chars <= max_chars and len(blocks) <= MAX_BLOCKS:
        return [blocks]

    pages: list[list[dict[str, Any]]] = []
    current_page: list[dict[str, Any]] = []
    current_chars = 0
    current_block_count = 0

    def flush_page(include_header: bool) -> None:
        nonlocal current_page, current_chars, current_block_count
        if include_header:
            page_blocks = header_context + current_page
        else:
            page_blocks = list(current_page)
        if page_blocks:
            pages.append(page_blocks)
        current_page = []
        current_chars = 0
        current_block_count = 0

    for blk in content_blocks:
        add_chars = _rich_text_len(blk)

        # Determine allowed blocks for this page considering header/context on first page
        max_blocks_this_page = MAX_BLOCKS - (len(header_context) if not pages else 0)

        # If adding this block would exceed constraints, flush the page
        if (
            current_page
            and (
                current_chars + add_chars > max_chars
                or current_block_count + 1 > max_blocks_this_page
            )
        ):
            flush_page(include_header=(len(pages) == 0))

        # If a single block itself would blow the char limit (shouldn't due to 2900
        # chunking), still start it on a new page to be safe.
        if not current_page and add_chars > max_chars:
            flush_page(include_header=(len(pages) == 0))

        # Add block
        current_page.append(blk)
        current_chars += add_chars
        current_block_count += 1

    # Flush the last page
    flush_page(include_header=(len(pages) == 0))

    return pages



def lambda_handler(event: dict[str, Any], _: Any) -> dict[str, Any]:
    """Entry point for Lambda proxy from Step Functions.

    Args:
        event: Expected to contain 'request_id' and 'result'.
            Tolerates variations.
    """
    # Resolve execution context
    request_id: str | None = (
        event.get("request_id")
        or event.get("Input", {}).get("request_id")
        or event.get("body", {}).get("request_id")
    )
    result_obj: Any = (
        event.get("result")
        or event.get("execute_result")
        or event.get("body")
        or event
    )

    if not request_id:
        # Nothing to do without a request id; return gracefully
        return {
            "statusCode": 200,
            "body": {"ok": False, "skipped": "missing_request_id"},
        }

    # DynamoDB lookup for Slack metadata
    table = get_approval_table()
    try:
        item = table.get_item(Key={"request_id": request_id}).get("Item") or {}
    except Exception:
        item = {}

    channel_id: str | None = item.get("slack_channel") or item.get(
        "channel_id"
    )
    ts: str | None = item.get("slack_ts") or item.get("ts")
    result_obj = item.get("completion_message")
    if not channel_id or not ts:
        # No Slack metadata to update; consider success
        return {
            "statusCode": 200,
            "body": {
                "ok": True,
                "updated": False,
                "reason": "no_slack_metadata",
            },
        }

    # Resolve token
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not bot_token:
        return {
            "statusCode": 200,
            "body": {"ok": False, "skipped": "no_token"},
        }

    # Build text and blocks from raw/markdown
    text = _extract_text_from_result(result_obj) or "Request completed."

    blocks, char_count = _build_blocks_from_text(text, request_id=request_id)
    print(f"blocks: {json.dumps(blocks, indent=4) }")

    # Split into multiple Slack messages if necessary. All pages are replies.
    pages = _paginate_blocks_for_slack_messages(blocks, max_chars=MAX_MESSAGE_CHARS)
    if not pages:
        pages = [blocks]

    # Post each page as a threaded reply
    total_pages = len(pages)
    for idx, page_blocks in enumerate(pages, start=1):
        suffix = "" if total_pages == 1 else f" ({idx}/{total_pages})"
        cont_text = f"Execution Result{suffix}"
        slack_blockkit.post_message_with_response(
            channel_id,
            cont_text,
            blocks=page_blocks,
            thread_ts=ts,
        )

    print(f"char_count: {char_count}")
    return {"statusCode": 200, "body": {"ok": True, "posted_replies": len(pages)}}


if __name__ == "__main__":
    event = {
        "message": "Request has been approved",
        "status": "approved",
        "request_id": "875814572ba88ea28723d4c03f7842c5b5613dcf2704676a5cefaed9cc179f68",
        "execute_result": {
            "statusCode": 200,
            "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
            },
            # "body": "Here's a cute cat GIF for you.\n\nEnjoy this adorable feline friend!\n\nhttps://media.tenor.com/0Q5IZ6e9pC8AAAAC/cat-cute-cat.gif\n\n"
            "body": """Based on the ClaimInformatics RAPID POC SOW document, here is the requested information:
### Industry: Healthcare
(Specifically focused on self-funded healthcare plans)
### AI Use Cases:
1. Insurance policy document analysis for compliance verification
2. Prompt-based report generation system for querying claim data
### Project Summary:
The ClaimInformatics AI Compliance POC successfully demonstrated the feasibility of using generative AI to enhance fiduciary oversight and payment integrity for self-funded healthcare plans. Leveraging AWS Bedrock for AI insights and Amazon Comprehend Medical for medical terminology extraction, the solution effectively analyzed insurance policy documents to verify compliance requirements and developed an intuitive prompt-based reporting system that allowed users to query claims data using natural language. The proof-of-concept implementation utilized AWS S3 for data storage, AWS Lambda for serverless computing, and Amazon API Gateway to create a seamless user interface. This innovative approach significantly reduced manual effort in compliance verification while enabling stakeholders to quickly generate custom reports from complex healthcare claims data, ultimately providing a foundation for a more comprehensive production solution. The ClaimInformatics AI Compliance POC successfully demonstrated the feasibility of using generative AI to enhance fiduciary oversight and payment integrity for self-funded healthcare plans. Leveraging AWS Bedrock for AI insights and Amazon Comprehend Medical for medical terminology extraction, the solution effectively analyzed insurance policy documents to verify compliance requirements and developed an intuitive prompt-based reporting system that allowed users to query claims data using natural language. The proof-of-concept implementation utilized AWS S3 for data storage, AWS Lambda for serverless computing, and Amazon API Gateway to create a seamless user interface. This innovative approach significantly reduced manual effort in compliance verification while enabling stakeholders to quickly generate custom reports from complex healthcare claims data, ultimately providing a foundation for a more comprehensive production solution. The ClaimInformatics AI Compliance POC successfully demonstrated the feasibility of using generative AI to enhance fiduciary oversight and payment integrity for self-funded healthcare plans. Leveraging AWS Bedrock for AI insights and Amazon Comprehend Medical for medical terminology extraction, the solution effectively analyzed insurance policy documents to verify compliance requirements and developed an intuitive prompt-based reporting system that allowed users to query claims data using natural language. The proof-of-concept implementation utilized AWS S3 for data storage, AWS Lambda for serverless computing, and Amazon API Gateway to create a seamless user interface. This innovative approach significantly reduced manual effort in compliance verification while enabling stakeholders to quickly generate custom reports from complex healthcare claims data, ultimately providing a foundation for a more comprehensive production solution. The ClaimInformatics AI Compliance POC successfully demonstrated the feasibility of using generative AI to enhance fiduciary oversight and payment integrity for self-funded healthcare plans. Leveraging AWS Bedrock for AI insights and Amazon Comprehend Medical for medical terminology extraction, the solution effectively analyzed insurance policy documents to verify compliance requirements and developed an intuitive prompt-based reporting system that allowed users to query claims data using natural language. The proof-of-concept implementation utilized AWS S3 for data storage, AWS Lambda for serverless computing, and Amazon API Gateway to create a seamless user interface. This innovative approach significantly reduced manual effort in compliance verification while enabling stakeholders to quickly generate custom reports from complex healthcare claims data, ultimately providing a foundation for a more comprehensive production solution. The ClaimInformatics AI Compliance POC successfully demonstrated the feasibility of using generative AI to enhance fiduciary oversight and payment integrity for self-funded healthcare plans. Leveraging AWS Bedrock for AI insights and Amazon Comprehend Medical for medical terminology extraction, the solution effectively analyzed insurance policy documents to verify compliance requirements and developed an intuitive prompt-based reporting system that allowed users to query claims data using natural language. The proof-of-concept implementation utilized AWS S3 for data storage, AWS Lambda for serverless computing, and Amazon API Gateway to create a seamless user interface. This innovative approach significantly reduced manual effort in compliance verification while enabling stakeholders to quickly generate custom reports from complex healthcare claims data, ultimately providing a foundation for a more comprehensive production solution. The ClaimInformatics AI Compliance POC successfully demonstrated the feasibility of using generative AI to enhance fiduciary oversight and payment integrity for self-funded healthcare plans. Leveraging AWS Bedrock for AI insights and Amazon Comprehend Medical for medical terminology extraction, the solution effectively analyzed insurance policy documents to verify compliance requirements and developed an intuitive prompt-based reporting system that allowed users to query claims data using natural language. The proof-of-concept implementation utilized AWS S3 for data storage, AWS Lambda for serverless computing, and Amazon API Gateway to create a seamless user interface. This innovative approach significantly reduced manual effort in compliance verification while enabling stakeholders to quickly generate custom reports from complex healthcare claims data, ultimately providing a foundation for a more comprehensive production solution. The ClaimInformatics AI Compliance POC successfully demonstrated the feasibility of using generative AI to enhance fiduciary oversight and payment integrity for self-funded healthcare plans. Leveraging AWS Bedrock for AI insights and Amazon Comprehend Medical for medical terminology extraction, the solution effectively analyzed insurance policy documents to verify compliance requirements and developed an intuitive prompt-based reporting system that allowed users to query claims data using natural language. The proof-of-concept implementation utilized AWS S3 for data storage, AWS Lambda for serverless computing, and Amazon API Gateway to create a seamless user interface. This innovative approach significantly reduced manual effort in compliance verification while enabling stakeholders to quickly generate custom reports from complex healthcare claims data, ultimately providing a foundation for a more comprehensive production solution. The ClaimInformatics AI Compliance POC successfully demonstrated the feasibility of using generative AI to enhance fiduciary oversight and payment integrity for self-funded healthcare plans. Leveraging AWS Bedrock for AI insights and Amazon Comprehend Medical for medical terminology extraction, the solution effectively analyzed insurance policy documents to verify compliance requirements and developed an intuitive prompt-based reporting system that allowed users to query claims data using natural language. The proof-of-concept implementation utilized AWS S3 for data storage, AWS Lambda for serverless computing, and Amazon API Gateway to create a seamless user interface. This innovative approach significantly reduced manual effort in compliance verification while enabling stakeholders to quickly generate custom reports from complex healthcare claims data, ultimately providing a foundation for a more comprehensive production solution."""
        }
    }
    print(lambda_handler(event, {}))
