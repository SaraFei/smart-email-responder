
# -*- coding: utf-8 -*-
import json
import os
import time
from dotenv import load_dotenv
load_dotenv()

def _get_user_display_name() -> str:
    """Fetch the user display name from the From header of a sent email."""
    try:
        from gmail_tools import get_gmail_service
        service = get_gmail_service()
        profile = service.users().getProfile(userId='me').execute()
        user_email = profile.get('emailAddress', '').lower()

        results = service.users().messages().list(
            userId='me', labelIds=['SENT'], maxResults=10
        ).execute()
        for msg in results.get('messages', []):
            full = service.users().messages().get(userId='me', id=msg['id']).execute()
            headers = full.get('payload', {}).get('headers', [])
            from_header = next((h['value'] for h in headers if h['name'] == 'From'), '')
            # Format: "Sarah Ravitz <sr7677876@gmail.com>"
            if '<' in from_header and user_email in from_header.lower():
                name = from_header.split('<')[0].strip().strip('"')
                if name and '@' not in name:
                    return name
        return "Your Name"
    except Exception:
        return "Your Name"

USER_NAME = _get_user_display_name()

from openai import OpenAI
from gmail_tools import search_emails, read_email_content, send_reply

client = OpenAI()

# Tools definition for OpenAI function calling
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_emails",
            "description": "Search Gmail for emails matching a subject or query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query, e.g. 'project proposal follow-up'"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_email_content",
            "description": "Read the full content of an email by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "The Gmail message ID"
                    }
                },
                "required": ["message_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_reply",
            "description": "Send a reply to an email thread.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body text"},
                    "message_id": {"type": "string", "description": "Original email Message-ID header for threading"},
                    "thread_id": {"type": "string", "description": "Gmail thread ID to reply within"}
                },
                "required": ["to", "subject", "body"]
            }
        }
    }
]

TOOL_FUNCTIONS = {
    "search_emails": search_emails,
    "read_email_content": read_email_content,
    "send_reply": send_reply,
}

SYSTEM_PROMPT = f"""You are an email assistant. You help users respond to their emails.

When searching for emails, ALWAYS return results in this EXACT format (no markdown, no bold):
ID: <message_id>
Thread-ID: <thread_id>
Message-ID: <message_id_header>
From: <sender>
Subject: <subject>
Preview: <snippet>

One blank line between each email result.
It is critical that Thread-ID is always included in every result — it is used internally by the system.

When the user selects an email:
1. Read its content using read_email_content
2. Draft a professional reply:
   - Extract the sender's name from the "From" field and use it
   - Sign the email with {USER_NAME}
   - Match the tone of the original email
   - Keep it concise and relevant
3. Present the draft between --- markers like this:
---
<draft here>
---
Then ask: "Would you like me to send this reply?"

When user approves:
- Send using send_reply with the thread_id
- For modifications, revise and show updated draft between --- markers again

Important:
- NEVER use markdown bold (**text**) in email listings
- Always include Thread-ID in search results
- Always use thread_id when sending to keep email in same thread
- When reading an email, check the "To" field. If the From is the user and To is someone else, reply TO that person — not back to the user
- The greeting "Dear X" must use the RECIPIENT's name (the person you are writing TO)
- The signature must use the SENDER's name (the user who is sending the reply)
- Never swap these two
- If a NOTE says "This email was sent by you to X and has not received a reply yet", draft a follow-up message addressed TO that recipient X, not to the user"""


def _call_openai_with_retry(messages: list, max_retries: int = 3, retry_delay: float = 2.0):
    """
    Call the OpenAI API with automatic retry on failure.
    Retries up to max_retries times with a delay between attempts.
    Raises RuntimeError if all attempts fail.
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            return client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                timeout=30.0
            )
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                print(f"\nAgent: OpenAI request failed (attempt {attempt}/{max_retries}). Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
    raise RuntimeError(f"OpenAI API unavailable after {max_retries} attempts: {last_error}")


def run_tool(tool_name: str, tool_args: dict) -> str:
    """Execute a tool and return the result as a string."""
    fn = TOOL_FUNCTIONS.get(tool_name)
    if not fn:
        return f"Unknown tool: {tool_name}"
    try:
        return fn(**tool_args)
    except Exception as e:
        return f"Error running {tool_name}: {e}"


def chat(messages: list) -> tuple[str, list]:
    """
    Send messages to OpenAI, handle tool calls, return final response.
    Returns (response_text, updated_messages)
    """
    while True:
        response = _call_openai_with_retry(messages)

        message = response.choices[0].message
        messages.append(message)

        if not message.tool_calls:
            return message.content, messages

        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)

            print(f"\nAgent: [Calling {tool_name}...]")
            result = run_tool(tool_name, tool_args)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result
            })