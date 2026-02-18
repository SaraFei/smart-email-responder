# -*- coding: utf-8 -*-
import os
import base64
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import html
from sanitizer import sanitize_email_content

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']


def _clean_snippet(raw_snippet: str, max_length: int = 120) -> str:
    """
    Decode HTML entities from a Gmail snippet and truncate cleanly.
    Truncates after decoding to avoid cutting in the middle of an entity.
    Strips any trailing incomplete word or stray punctuation after truncation.
    """
    decoded = html.unescape(raw_snippet)
    if len(decoded) <= max_length:
        return decoded
    truncated = decoded[:max_length]
    # Remove trailing incomplete word or stray character after last space
    last_space = truncated.rfind(' ')
    if last_space > max_length // 2:
        truncated = truncated[:last_space]
    return truncated + '...'


# Common typo corrections for email search
def _levenshtein(a: str, b: str) -> int:
    """Calculate the edit distance between two strings."""
    rows, cols = len(a) + 1, len(b) + 1
    dp = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        dp[i][0] = i
    for j in range(cols):
        dp[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[i][j] = min(dp[i-1][j] + 1, dp[i][j-1] + 1, dp[i-1][j-1] + cost)
    return dp[-1][-1]


def _suggest_correction(query: str, found_subjects: list[str]) -> str:
    """
    Suggest the closest word from email subjects using Levenshtein distance.
    Only suggests if the distance is small enough to be a plausible typo.
    """
    query_lower = query.lower()
    best_word = ""
    best_score = float("inf")

    for subject in found_subjects:
        for word in subject.lower().split():
            if len(word) < 3:
                continue
            distance = _levenshtein(query_lower, word)
            # Allow up to 2 edits, and only if the word is not much longer
            max_allowed = min(2, len(query_lower) // 2)
            if distance <= max_allowed and distance < best_score:
                best_score = distance
                best_word = word

    return best_word



def suggest_search_correction(query: str) -> str:
    """
    Public function: uses pyspellchecker to correct typos in the search query.
    If a correction is found, searches Gmail with the corrected term.
    Called directly from main.py when no emails were found for the search term.
    """
    try:
        from spellchecker import SpellChecker
        spell = SpellChecker()
        corrected = spell.correction(query.lower())
        if corrected and corrected != query.lower():
            return corrected
        return ""
    except ImportError:
        return ""
    except Exception:
        return ""

def get_last_reply(thread_id: str) -> str:
    """
    Checks if the user was the last to reply in this thread.
    Returns the snippet of their last reply, or empty string if they were not last.
    """
    try:
        service = get_gmail_service()
        profile = service.users().getProfile(userId='me').execute()
        user_email = profile.get('emailAddress', '').lower()

        thread = service.users().threads().get(userId='me', id=thread_id).execute()
        messages = thread.get('messages', [])

        if not messages:
            return ""

        # If the thread has only one message and it was sent by the user,
        # this is an outgoing email the user created — not a reply.
        # Only flag as "already replied" if the user sent a message AFTER the first one.
        first_msg_headers = messages[0].get('payload', {}).get('headers', [])
        first_sender = next((h['value'] for h in first_msg_headers if h['name'] == 'From'), '').lower()
        user_created_thread = user_email in first_sender

        if user_created_thread and len(messages) == 1:
            return ""

        last_msg = messages[-1]
        headers = last_msg.get('payload', {}).get('headers', [])
        sender = next((h['value'] for h in headers if h['name'] == 'From'), '').lower()

        if user_email in sender:
            # Make sure it's not just the original message
            if user_created_thread and last_msg == messages[0]:
                return ""
            snippet = _clean_snippet(last_msg.get('snippet', ''))
            return snippet

        return ""

    except Exception:
        return ""


def check_already_replied(thread_id: str) -> bool:
    """Check if the user has already sent a reply in this email thread."""
    try:
        service = get_gmail_service()
        profile = service.users().getProfile(userId='me').execute()
        user_email = profile.get('emailAddress', '').lower()

        thread = service.users().threads().get(userId='me', id=thread_id).execute()
        messages = thread.get('messages', [])

        for msg in messages[1:]:
            headers = msg.get('payload', {}).get('headers', [])
            sender = next((h['value'] for h in headers if h['name'] == 'From'), '').lower()
            if user_email in sender:
                return True
        return False

    except Exception:
        return False


def get_gmail_service():
    """Authenticate and return Gmail API service."""
    creds = None

    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                raise FileNotFoundError(
                    "credentials.json not found. "
                    "Please download it from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)


def search_emails(query: str) -> str:
    """Search Gmail and return one result per thread."""
    try:
        service = get_gmail_service()
        results = service.users().messages().list(
            userId='me', q=query, maxResults=10
        ).execute()
        messages = results.get('messages', [])

        if not messages:
            broad_results = service.users().messages().list(
                userId='me', q=query[:3], maxResults=5
            ).execute()
            broad_messages = broad_results.get('messages', [])

            if broad_messages:
                subjects = []
                for msg in broad_messages[:3]:
                    full = service.users().messages().get(userId='me', id=msg['id']).execute()
                    headers = full.get('payload', {}).get('headers', [])
                    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
                    if subject:
                        subjects.append(subject)

                suggestion = _suggest_correction(query, subjects)
                if suggestion:
                    return f"No emails found for '{query}'. Did you mean '{suggestion}'? Try searching again."

            return f"No emails found for '{query}'. Please try different keywords."

        seen_threads = set()
        summaries = []

        for msg in messages:
            full = service.users().messages().get(userId='me', id=msg['id']).execute()
            thread_id = full.get('threadId', '')

            if thread_id in seen_threads:
                continue
            seen_threads.add(thread_id)

            headers = full.get('payload', {}).get('headers', [])
            subject  = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            sender   = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
            msg_id   = next((h['value'] for h in headers if h['name'] == 'Message-ID'), '')
            snippet  = _clean_snippet(full.get('snippet', ''))

            last_reply = get_last_reply(thread_id)
            replied_note = (
                f"\n[NOTE: You already replied to this thread. "
                f"Your last reply was: \"{last_reply}\"]"
            ) if last_reply else ""

            # Check if this is an outgoing email with no reply yet
            service2 = get_gmail_service()
            thread_data = service2.users().threads().get(userId='me', id=thread_id).execute()
            thread_messages = thread_data.get('messages', [])
            profile = service2.users().getProfile(userId='me').execute()
            user_email = profile.get('emailAddress', '').lower()
            first_headers = thread_messages[0].get('payload', {}).get('headers', []) if thread_messages else []
            first_sender = next((h['value'] for h in first_headers if h['name'] == 'From'), '').lower()
            to_address = next((h['value'] for h in first_headers if h['name'] == 'To'), '')
            if user_email in first_sender and len(thread_messages) == 1:
                replied_note = f"\n[NOTE: This email was sent by you to {to_address} and has not received a reply yet.]"

            summaries.append(
                f"ID: {msg['id']}\n"
                f"Thread-ID: {thread_id}\n"
                f"Message-ID: {msg_id}\n"
                f"From: {sender}\n"
                f"Subject: {subject}\n"
                f"Preview: {snippet}"
                f"{replied_note}"
            )

        return "\n\n".join(summaries)

    except HttpError as e:
        return f"Gmail API error: {e}"
    except Exception as e:
        return f"Search error: {e}"


def read_email_content(message_id: str) -> str:
    """
    Return the full content of an email thread.
    Always reads the first message in the thread to identify the original sender/recipient.
    Also returns the last message to provide context of the latest reply.
    """
    try:
        service = get_gmail_service()
        profile = service.users().getProfile(userId='me').execute()
        user_email = profile.get('emailAddress', '').lower()

        # Get the message to find its thread
        message = service.users().messages().get(
            userId='me', id=message_id.strip(), format='full'
        ).execute()
        thread_id = message.get('threadId', '')

        # Get the full thread
        thread = service.users().threads().get(userId='me', id=thread_id).execute()
        thread_messages = thread.get('messages', [])

        # Always read the first message to get original sender/recipient
        first_msg = thread_messages[0]
        headers = first_msg.get('payload', {}).get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
        sender  = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
        to      = next((h['value'] for h in headers if h['name'] == 'To'), '')
        date    = next((h['value'] for h in headers if h['name'] == 'Date'), 'Unknown')
        body    = sanitize_email_content(_extract_body(first_msg.get('payload', {})))

        to_line = f"\nTo: {to}" if to else ""

        # If user sent the first message, clarify who to reply to
        if user_email in sender.lower():
            note = f"\n[NOTE: You sent this email to {to}. Draft a follow-up to {to}.]"
        else:
            note = ""

        return f"From: {sender}{to_line}\nDate: {date}\nSubject: {subject}{note}\n\n{body}"

    except HttpError as e:
        return f"Gmail API error: {e}"
    except Exception as e:
        return f"Read error: {e}"


def _extract_body(payload: dict) -> str:
    """Recursively extract plain-text body from email payload."""
    parts = payload.get('parts', [])

    if not parts:
        data = payload.get('body', {}).get('data')
        if data:
            return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
        return 'No content found.'

    for part in parts:
        if part.get('mimeType') == 'text/plain':
            data = part.get('body', {}).get('data')
            if data:
                return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')

    for part in parts:
        result = _extract_body(part)
        if result != 'No content found.':
            return result

    return 'No content found.'


def send_reply(to: str, subject: str, body: str, message_id: str = None, thread_id: str = None) -> str:
    """Send a reply to an existing email thread."""
    try:
        service = get_gmail_service()
        email = EmailMessage()
        email.set_content(body)
        email['To'] = to.strip()
        email['Subject'] = subject.strip() if subject.startswith('Re:') else f"Re: {subject.strip()}"

        if message_id:
            email['In-Reply-To'] = message_id
            email['References'] = message_id

        raw = base64.urlsafe_b64encode(email.as_bytes()).decode()
        send_body = {'raw': raw}
        if thread_id:
            send_body['threadId'] = thread_id

        service.users().messages().send(userId='me', body=send_body).execute()
        return f"Reply sent successfully to {to}"

    except HttpError as e:
        return f"Gmail API error: {e}"
    except Exception as e:
        return f"Send error: {e}"