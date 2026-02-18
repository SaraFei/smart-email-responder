# 📬 AI Email Response Agent

An intelligent CLI agent that reads your Gmail inbox, understands context, and drafts professional replies — with your approval before anything is sent.

Built as a technical assessment project, this agent goes well beyond the basic requirements with a production-grade architecture and multiple safety layers.

---

## ✨ Features

- **Smart email search** — typo correction powered by `pyspellchecker` (e.g. `likw` → searches `like`)
- **Context-aware drafting** — detects whether you're replying to someone or sending a follow-up, and drafts accordingly
- **Human-in-the-loop** — every draft requires explicit approval before sending. Supports approve / reject / modify
- **PII redaction** — phone numbers, email addresses, and IDs are masked before reaching OpenAI
- **Prompt injection protection** — malicious content in emails is detected and blocked
- **Draft validation** — checks for unfilled placeholders and formatting issues before presenting the draft
- **Already-replied detection** — warns you if you've already responded to a thread
- **Retry logic** — automatically retries failed OpenAI requests up to 3 times with a 30-second timeout
- **Dynamic sender name** — reads your display name directly from Gmail, no hardcoding

---

## 🏗️ Architecture

```
User Input
  → Gmail Search (direct API call, not LLM)
  → Typo correction if no results found
  → Email selected by user
  → Read full thread (first message = original context)
  → Sanitization: HTML strip + injection detection + PII redaction
  → OpenAI drafts reply
  → Validation: placeholders, length, markers
  → Human approval
  → Send via Gmail API
```

Each file has a single responsibility:

| File | Role |
|---|---|
| `main.py` | User flow and interaction |
| `agent.py` | OpenAI communication and retry logic |
| `gmail_tools.py` | Gmail API: search, read, send |
| `sanitizer.py` | Input safety: injection + PII |
| `validator.py` | Output quality: draft validation |

---

## 🚀 Setup

### 1. Clone the project and activate virtual environment

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac / Linux
pip install -r requirements.txt
```

### 2. Create a `.env` file

```
OPENAI_API_KEY=your_openai_api_key_here
```

### 3. Google Cloud Project & Gmail API

Follow these exact steps to enable the agent to access your Gmail:

1. **Create a Project** — Go to [Google Cloud Console](https://console.cloud.google.com/) and create a new project.

2. **Enable API** — Navigate to **APIs & Services > Library**, search for **Gmail API**, and click **Enable**.

3. **OAuth Consent Screen**
   - Go to **APIs & Services > OAuth consent screen**
   - Select **External** and fill in the required app details
   - **Test Users (Required):** Under "Test users", click **+ ADD USERS** and add the Gmail address you will use for testing. Without this, you will receive an "Access Blocked" error.

4. **Create Credentials**
   - Go to **APIs & Services > Credentials**
   - Click **+ CREATE CREDENTIALS > OAuth client ID**
   - Select **Application type: Desktop App**
   - Download the JSON file, rename it to `credentials.json`, and place it in the project root

On first run, a browser will open automatically asking you to authorize Gmail access. A `token.json` will be created automatically — no further steps needed.

---

## ▶️ Run

```bash
python main.py
```

---

## 🔒 Security Notes

- `credentials.json`, `token.json`, and `.env` are in `.gitignore` and must never be committed
- All sensitive data is redacted before reaching OpenAI
- No email is ever sent without explicit user confirmation
