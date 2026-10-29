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
- `/digest` – digest now · `/categories` – list categories and blocked sites · `/unblock <site>` – crawl a blocked site again · `/reset` – clear chat memory

Only your chat ID can use the bot; it ignores everyone else.

How the digest is made:

1. **Headlines.** Each category has 3–6 broad Google News searches (synonyms, trade sites, Korean). Posts from social and video platforms (Instagram, X, YouTube, etc.) are dropped.
2. **Pick (Sonnet, low effort).** Claude Sonnet reads the few hundred headlines and picks about 20 stories by importance. Every category with real news gets at least its top story, and each category is judged by its own description (for South Korea, the biggest stories in Korea, not just ones about identity or AI).
3. **Read.** The bot downloads each picked article and keeps its text.
4. **Key facts (Sonnet, low effort).** Sonnet reads the articles and writes notes: up to 15 stories, each with facts taken from the article (names and figures copied exactly) and why it matters to you. It leaves out paywall teasers and pages that don't match the headline. Picked stories whose articles couldn't be read can still appear, marked *headline only*, with nothing added beyond the headline.
5. **Write (Haiku).** Claude Haiku writes the digest from those notes only. If it uses a number that isn't in the notes, the bot sends the notes as written instead.

If fewer than 5 articles load, the digest falls back to headlines only and says so.

**Blocked sites.** When a site refuses the download (HTTP 401/402/403/451) or returns no readable article (a paywall, or a page that needs a browser), the bot stops trying to download it. Its stories can still be picked, and appear as *headline only*. `/categories` lists those sites; `/unblock reuters.com` tries reading one again. If no article loads at all, nothing is blocked, since the problem is more likely on the bot's side.

A digest costs roughly 10–15 cents ($2–3 a month on weekdays); `compare_models.py` measures it. Chat replies use Claude Haiku with web search. `/categories` shows each category's searches; ask the bot in chat to change them.

## Optional settings

| Variable | Default |
|---|---|
| `NEWSBOT_EDITOR_MODEL` | `claude-sonnet-5-5` (picks stories, pulls key facts from articles) |
| `NEWSBOT_WRITER_MODEL` | `claude-haiku-5-5` (writes the digest from the editor's notes) |
| `NEWSBOT_MODEL` | `claude-haiku-5-5` (chat replies) |
| `NEWSBOT_TZ` | `America/Los_Angeles` |
| `NEWSBOT_STATE` | `state.json` next to `bot.py` (categories, last digest, chat memory) |

The bot must be running to send the digest and answer you. Your computer works while it's on; for always-on, host it on a small server (e.g. Railway, Render, Fly.io) with the same environment variables.

## Comparing digests

`python compare_models.py` fetches today's headlines once, then writes the digest two ways from them: from the articles (the steps above) and from headlines alone (Sonnet). It prints each one's tokens and cost per model and saves them as `digest-<name>.html` to read side by side. To compare headline-only digests from other models instead, name them: `python compare_models.py claude-haiku-5-5 claude-sonnet-5-5`. It needs only `ANTHROPIC_API_KEY` and sends nothing to Telegram, but sites that block the download are saved, as in a real digest.
