
# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv
from agent import chat, SYSTEM_PROMPT
from validator import validate_draft
from gmail_tools import get_last_reply, suggest_search_correction, search_emails

load_dotenv()


def extract_draft(response: str) -> str:
    """Extract just the draft text from agent response."""
    if '---' in response:
        parts = response.split('---')
        if len(parts) >= 3:
            return parts[1].strip()
    return response.strip()


def parse_email_results(response: str) -> list[dict]:
    """Parse agent response into list of emails."""
    emails = []
    blocks = response.strip().split('\n\n')
    for block in blocks:
        if 'From:' in block and 'Subject:' in block:
            email = {}
            for line in block.split('\n'):
                if line.startswith('ID:'):
                    email['id'] = line.replace('ID:', '').strip()
                elif line.startswith('Thread-ID:'):
                    email['thread_id'] = line.replace('Thread-ID:', '').strip()
                elif line.startswith('From:'):
                    email['from'] = line.replace('From:', '').strip()
                elif line.startswith('Subject:'):
                    email['subject'] = line.replace('Subject:', '').strip()
                elif line.startswith('Preview:'):
                    email['preview'] = line.replace('Preview:', '').strip()
                elif line.startswith('[NOTE:'):
                    email['note'] = line.strip()
            if email:
                emails.append(email)
    return emails


def display_email_selection(emails: list[dict]) -> int:
    """Display emails and ask user to pick one. Returns selected index (0-based) or -1."""
    if len(emails) == 1:
        print(f"\nAgent: I found this email:")
        print(f"   From:    {emails[0].get('from', 'Unknown')}")
        print(f"   Subject: {emails[0].get('subject', 'No subject')}")
        print(f"   Preview: {emails[0].get('preview', '')}")
        if emails[0].get('note'):
            print(f"   {emails[0]['note']}")
        print()
        confirm = input("Is this the email you meant? (y=yes / n=no): ").strip().lower()
        return 0 if confirm in ['yes', 'y'] else -1
    else:
        print(f"\nAgent: I found {len(emails)} emails matching your search:\n")
        for i, email in enumerate(emails, 1):
            print(f"   {i}. From:    {email.get('from', 'Unknown')}")
            print(f"      Subject: {email.get('subject', 'No subject')}")
            print(f"      Preview: {email.get('preview', '')}")
            if email.get('note'):
                print(f"      {email['note']}")
            print()
        while True:
            choice = input(f"Which email would you like to respond to? (1-{len(emails)} / n=no): ").strip().lower()
            if choice in ['no', 'n']:
                return -1
            if choice.isdigit() and 1 <= int(choice) <= len(emails):
                return int(choice) - 1
            print(f"Please enter a number between 1 and {len(emails)}, or 'n'.")


def check_already_replied(selected: dict) -> bool:
    """
    Check if the user already replied to the selected email thread.
    If so, display a message and ask whether to proceed.
    Returns True if we should continue drafting, False if we should abort.
    """
    thread_id = selected.get('thread_id', '')

    if not thread_id:
        return True

    last_reply = get_last_reply(thread_id)

    if last_reply:
        print(f"\nAgent: You have already replied to this thread.")
        print(f"   Your last reply was: \"{last_reply}\"")
        print()
        proceed = input("Do you still want to draft another reply? (y=yes / n=no): ").strip().lower()
        return proceed in ['yes', 'y']

    return True


def search_and_select(messages: list) -> tuple[dict | None, list]:
    """
    Ask the user for a subject, search Gmail, and return the selected email.
    Checks Gmail directly first — if no results, shows fuzzy suggestion before sending to agent.
    Returns (selected_email, updated_messages), or (None, messages) if user wants to exit.
    """
    subject = input("Which email would you like to respond to? ").strip()
    if not subject:
        print("No subject provided. Exiting.")
        return None, messages

    print("\nAgent: Searching for that email...")

    # Check Gmail directly before involving the agent
    raw_result = search_emails(subject)
    if "no emails found" in raw_result.lower() or "search error" in raw_result.lower():
        suggestion = suggest_search_correction(subject)
        if suggestion:
            # Search immediately with the corrected word
            corrected_result = search_emails(suggestion)
            if "no emails found" not in corrected_result.lower():
                # Parse and display results cleanly, then ask if correction was intended
                messages.append({"role": "user", "content": f"Search for emails about: {suggestion}. List all results."})
                response, messages = chat(messages)
                emails_corrected = parse_email_results(response)
                if emails_corrected:
                    print(f"\nAgent: Did you mean '{suggestion}'? Here are the results:\n")
                    for i, email in enumerate(emails_corrected, 1):
                        print(f"   {i}. From:    {email.get('from', 'Unknown')}")
                        print(f"      Subject: {email.get('subject', 'No subject')}")
                        print(f"      Preview: {email.get('preview', '')}")
                        print()
                confirm = input("Is this what you meant? (y=yes / n=no): ").strip().lower()
                if confirm in ['yes', 'y']:
                    subject = suggestion
                    # Fall through to email selection below using already-fetched emails
                    selected_index = display_email_selection(emails_corrected)
                    if selected_index == -1:
                        retry = input("\nWould you like to search again? (y=yes / n=no): ").strip().lower()
                        if retry in ['yes', 'y']:
                            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                            return search_and_select(messages)
                        print("Agent: Goodbye!")
                        return None, messages
                    return emails_corrected[selected_index], messages
                else:
                    retry = input("Would you like to search again? (y=yes / n=no): ").strip().lower()
                    if retry in ['yes', 'y']:
                        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                        return search_and_select(messages)
                    print("Agent: Goodbye!")
                    return None, messages
            else:
                print(f"\nAgent: No emails found for '{subject}' or '{suggestion}'. Please try different keywords.")
                print()
                retry = input("Would you like to search again? (y=yes / n=no): ").strip().lower()
                if retry in ['yes', 'y']:
                    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                    return search_and_select(messages)
                print("Agent: Goodbye!")
                return None, messages
        else:
            print(f"\nAgent: No emails found for '{subject}'. Please try different keywords.")
            print()
            retry = input("Would you like to search again? (y=yes / n=no): ").strip().lower()
            if retry in ['yes', 'y']:
                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                return search_and_select(messages)
            print("Agent: Goodbye!")
            return None, messages

    # Results found — let the agent format and present them
    messages.append({"role": "user", "content": f"Search for emails about: {subject}. List all results."})
    response, messages = chat(messages)

    emails = parse_email_results(response)
    if not emails:
        print(f"\nAgent: {response}\n")
        retry = input("Would you like to search again? (y=yes / n=no): ").strip().lower()
        if retry in ['yes', 'y']:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            return search_and_select(messages)
        return None, messages

    selected_index = display_email_selection(emails)
    if selected_index == -1:
        retry = input("\nWould you like to search again? (y=yes / n=no): ").strip().lower()
        if retry in ['yes', 'y']:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            return search_and_select(messages)
        print("Agent: Goodbye!")
        return None, messages

    return emails[selected_index], messages


def draft_reply(selected: dict, messages: list) -> tuple[str, list]:
    """
    Read the selected email and generate a draft reply.
    Returns (response_text, updated_messages).
    """
    print(f"\nAgent: Got it! Let me draft a reply to '{selected.get('subject', '')}'...")
    messages.append({"role": "user", "content": f"Read and draft a reply for email ID: {selected.get('id', '')}"})
    response, messages = chat(messages)
    print(f"\nAgent: {response}\n")

    draft = extract_draft(response)
    validation = validate_draft(draft)
    if validation.has_issues():
        print("-" * 50)
        print(validation.summary())
        print("-" * 50)
        if validation.errors:
            print("\nAgent: Let me fix those issues automatically...")
            messages.append({"role": "user", "content": f"Fix these issues: {', '.join(validation.errors)}"})
            response, messages = chat(messages)
            print(f"\nAgent: {response}\n")

    return response, messages


def confirm_and_send(messages: list) -> tuple[bool, list]:
    """
    Ask the user to approve, reject, or modify the draft.
    Returns (should_continue_to_next_email, updated_messages).
    """
    while True:
        user_input = input("Your response (y=yes / n=no / m=modify): ").strip().lower()

        if user_input in ['yes', 'y', 'approve', 'send']:
            messages.append({"role": "user", "content": "Yes, please send it."})
            response, messages = chat(messages)
            print(f"\nAgent: {response}")
            another = input("\nWould you like to respond to another email? (y=yes / n=no): ").strip().lower()
            return another in ['yes', 'y'], messages

        elif user_input in ['no', 'n', 'reject', 'cancel']:
            print("\nAgent: Reply cancelled.")
            another = input("\nWould you like to respond to another email? (y=yes / n=no): ").strip().lower()
            return another in ['yes', 'y'], messages

        elif user_input in ['modify', 'm']:
            modification = input("How would you like to modify the reply? ").strip()
            if not modification:
                print("No modification provided.")
                continue
            messages.append({"role": "user", "content": f"Please modify the draft: {modification}"})
            response, messages = chat(messages)
            print(f"\nAgent: {response}\n")
            draft = extract_draft(response)
            validation = validate_draft(draft)
            if validation.has_issues():
                print("-" * 50)
                print(validation.summary())
                print("-" * 50 + "\n")

        else:
            print("Please enter y=yes, n=no, or m=modify.")


def main():
    print("\n=== Email Response Agent ===")
    print("I can help you respond to your emails.\n")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        selected, messages = search_and_select(messages)
        if selected is None:
            return

        if not check_already_replied(selected):
            print("Agent: Understood, skipping this email.")
            another = input("\nWould you like to respond to another email? (y=yes / n=no): ").strip().lower()
            if another in ["yes", "y"]:
                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                continue
            print("Agent: Goodbye!")
            return

        _, messages = draft_reply(selected, messages)

        should_continue, messages = confirm_and_send(messages)
        if not should_continue:
            print("Agent: Goodbye!")
            return

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nAgent stopped by user.")
    except RuntimeError as e:
        print(f"\nAgent: {e}")
        print("Please check your internet connection and try again.")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()