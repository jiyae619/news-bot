# News Watch – Telegram bot

Your daily news digest, delivered in Telegram, and a chat you can talk to.

## Setup (once, ~10 minutes)

1. **Create the bot.** In Telegram, message `@BotFather`, send `/newbot`, follow the prompts, copy the token.
2. **Get a Claude API key** at https://console.anthropic.com (add a few dollars of credit).
3. **Install** (Python 3.10+):
   ```bash
   cd news-bot
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
4. **Find your chat ID.** Run the bot once without it:
   ```bash
   export TELEGRAM_BOT_TOKEN=...   ANTHROPIC_API_KEY=...
   python bot.py
   ```
   Send `/start` to your bot in Telegram. It replies with your chat ID. Stop the bot (Ctrl+C).
5. **Run for real:**
   ```bash
   export TELEGRAM_CHAT_ID=123456789
   python bot.py
   ```

## Using it

- Digest arrives weekdays (Monday–Friday) at 7:45am Pacific (items are numbered).
- Just text it: "more on 4", "add a category for crypto regulation", "drop Fintech", "what's the latest on passkeys?"
- `/digest` – digest now · `/categories` – list categories · `/reset` – clear chat memory

Only your chat ID can use the bot; it ignores everyone else.

The digest is built from free Google News feeds: each category has 3–5 broad search queries (synonyms, trade sites, Korean), and Claude reads the few hundred headlines they return and picks the 15 most relevant stories, at least 2 per category. That costs about a tenth of a cent per digest. Chat replies still use Claude's web search for details. `/categories` shows each category's searches; ask the bot in chat to change them.

## Optional settings

| Variable | Default |
|---|---|
| `NEWSBOT_MODEL` | `claude-haiku-5-5` (cheapest; `claude-sonnet-5-5` or `claude-opus-5-5` for higher-quality digests) |
| `NEWSBOT_TZ` | `America/Los_Angeles` |
| `NEWSBOT_STATE` | `state.json` next to `bot.py` (categories, last digest, chat memory) |

The bot must be running to send the digest and answer you. Your computer works while it's on; for always-on, host it on a small server (e.g. Railway, Render, Fly.io) with the same environment variables.
