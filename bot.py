"""News Watch Telegram bot.

- Sends a daily news digest to your Telegram chat (replaces the email).
- Lets you chat with it: ask follow-ups, get more detail, add or drop categories.
"""

import datetime as dt
import html
import json
import logging
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import feedparser
import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("newsbot")

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))  # only this chat may use the bot
MODEL = os.environ.get("NEWSBOT_MODEL", "claude-haiku-5-5")
TZ = ZoneInfo(os.environ.get("NEWSBOT_TZ", "America/Los_Angeles"))
DIGEST_TIME = dt.time(hour=7, minute=45, tzinfo=TZ)
DIGEST_DAYS = (1, 2, 3, 4, 5)  # Monday-Friday (0 is Sunday)
STATE_FILE = Path(os.environ.get("NEWSBOT_STATE", Path(__file__).with_name("state.json")))
HISTORY_LIMIT = 10  # chat messages kept as context; each one is resent with every message

client = anthropic.AsyncAnthropic()

NEWS_FEED_URL = "https://news.google.com/rss/search"
ITEMS_PER_QUERY = 10  # newest headlines kept from each news feed query

DEFAULT_CATEGORIES = [
    {"name": "Fraud & Risk", "description": "Payment fraud, scams, account takeover, deepfake fraud, risk and fraud-prevention products, notable fraud incidents or enforcement actions.",
     "queries": ['"payment fraud" OR scam OR "account takeover"', '"deepfake fraud" OR "fraud prevention"']},
    {"name": "Identity", "description": "Identity verification, biometrics, digital ID and wallets, authentication, passkeys, non-human and AI agent identity, IAM.",
     "queries": ['"identity verification" OR biometrics OR "digital ID"', 'passkeys OR "AI agent identity" OR "identity and access management"']},
    {"name": "Fintech", "description": "Product launches, funding and M&A, regulation, and notable moves by fintech companies and banks.",
     "queries": ['fintech funding OR acquisition OR launch', 'fintech regulation OR neobank']},
    {"name": "AI Governance", "description": "AI regulation and policy (EU AI Act, US federal and state, other countries), standards (NIST, ISO 42001), AI safety and Responsible AI news, enforcement and lawsuits.",
     "queries": ['"AI Act" OR "AI regulation" OR "AI policy"', '"AI safety" OR "responsible AI" OR "AI lawsuit"']},
    {"name": "South Korea", "description": "The day's biggest South Korean stories across politics, economy, business, society, tech, and international relations. Search in both English and Korean.",
     "queries": ['"South Korea"', '한국 경제 OR 정치 OR 사회']},
]
DEFAULT_QUERIES = {c["name"]: c["queries"] for c in DEFAULT_CATEGORIES}

PROFILE = (
    "The reader is Joy, a product manager working in identity, security governance, "
    "and Responsible AI / Trust & Safety."
)

FORMAT_RULES = """Formatting: this is shown in Telegram, so use ONLY these HTML tags: <b>, <i>, <a href="...">.
No Markdown, no headings with #, no <p>, <br>, <ul> or <li>. Use plain newlines and "• " for bullets.
Escape any literal &, < or > in text as &amp; &lt; &gt;. Keep it scannable and in plain, natural language. No hype."""

DIGEST_PROMPT = """{profile}

Write today's digest for these categories:
{categories}

Below are news headlines from the last 24 hours, grouped by category. Each line is: headline (source) link.
<news>
{news}
</news>

Rules:
- Use only the items above. Never add stories from memory, and use each item's link exactly as given.
- You only have headlines, so say what happened plainly and don't invent details the headline doesn't give.
- Skip duplicate coverage of the same story (pick the most credible source), off-topic items, press-release fluff and listicles.
- Maximum 5 items per category. Fewer is fine; if nothing is worth noting, write "Nothing notable today."
- Prefer credible primary or trade sources (Reuters, Bloomberg, FT, AP, regulator sites, Biometric Update, Finextra, The Record, Korea Herald, Korea JoongAng Daily, Yonhap, etc.).

Digest format:
- First line: <b>News Watch — {date}</b>
- For each category: a bold category name, then numbered items. Number items continuously across the whole digest (1, 2, 3...) so the reader can say "more on 7".
- Each item: <b>Headline</b> (Source) — one plain sentence on why it matters to the reader, then <a href="URL">Read more</a>. Write Korean headlines in English.
- End with a short <b>Worth a closer look</b> list of the 2–3 most important items.
- Output only the digest, nothing before or after it.

{format_rules}"""

CHAT_SYSTEM = """You are News Watch, a personal news assistant Joy talks to over Telegram. {profile}

Today is {date}. Joy's current news categories:
{categories}

What you do:
- Answer questions about the news, give more detail on a digest item ("more on 3"), and find related coverage. Use web search for anything current, and always include links to sources.
- When Joy asks to add, remove, rename or refocus a category, call update_categories with the complete new list, then confirm briefly.
- If Joy asks for a fresh digest now, tell her to send /digest.
- Keep replies short: a few sentences or bullets, each with a link where relevant.

The most recent digest sent to Joy is below for reference (item numbers refer to it):
<last_digest>
{last_digest}
</last_digest>

{format_rules}"""

UPDATE_CATEGORIES_TOOL = {
    "name": "update_categories",
    "description": "Replace Joy's full list of news categories. Pass every category that should remain, including unchanged ones.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "categories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Short category name"},
                        "description": {"type": "string", "description": "What to search for in this category"},
                        "queries": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "1-3 short Google News search queries for this category: keywords, quoted phrases and OR. Write a query in Korean to get Korean-language news.",
                        },
                    },
                    "required": ["name", "description", "queries"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["categories"],
        "additionalProperties": False,
    },
}

IS_HAIKU = "haiku" in MODEL
# Haiku supports only the basic web search tool and has no server-side refusal fallback.
# Each search costs about a cent and adds a lot of input, so the digest reads free news feeds instead.
WEB_SEARCH_TYPE = "web_search_20250305" if IS_HAIKU else "web_search_20260209"
CHAT_SEARCH_TOOL = {"type": WEB_SEARCH_TYPE, "name": "web_search", "max_uses": 3}
FALLBACK_ARGS = {} if IS_HAIKU else {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}


# ---------- state ----------

def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"categories": DEFAULT_CATEGORIES, "last_digest": "", "history": []}
    state = json.loads(STATE_FILE.read_text())
    for c in state["categories"]:  # categories saved before news feeds had no queries
        c.setdefault("queries", DEFAULT_QUERIES.get(c["name"], [c["name"]]))
    return state


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def format_categories(categories: list[dict]) -> str:
    return "\n".join(f"{i}. {c['name']}: {c['description']}" for i, c in enumerate(categories, 1))


def today() -> str:
    return dt.datetime.now(TZ).strftime("%A, %B %-d, %Y")


# ---------- Claude ----------

async def run_claude(system: str, messages: list[dict], tools: list[dict], effort: str, state: dict) -> str:
    """Run Claude until it finishes, handling web-search pauses and the update_categories tool."""
    messages = list(messages)
    text = []  # a paused turn resumes where it left off, so keep text from every response
    for _ in range(10):
        response = await client.beta.messages.create(
            model=MODEL,
            max_tokens=21000,  # most the SDK allows without streaming; reasoning counts toward it
            system=system,
            messages=messages,
            **({"tools": tools} if tools else {}),
            output_config={"effort": effort},
            **FALLBACK_ARGS,
        )
        log.info("Claude stop_reason=%s input_tokens=%s output_tokens=%s",
                 response.stop_reason, response.usage.input_tokens, response.usage.output_tokens)
        if response.stop_reason == "refusal":
            return "Sorry, I couldn't answer that one."

        text += [b.text for b in response.content if b.type == "text"]

        if response.stop_reason == "pause_turn":
            # Server-side web search hit its loop limit; resend so it resumes.
            messages.append({"role": "assistant", "content": response.content})
            continue

        if response.stop_reason == "tool_use":
            text = []  # the answer comes after the tool result
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if block.name == "update_categories":
                    state["categories"] = block.input["categories"]
                    save_state(state)
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": "Saved:\n" + format_categories(state["categories"])})
                else:
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"Unknown tool {block.name}", "is_error": True})
            messages.append({"role": "user", "content": results})
            continue

        reply = "".join(text).strip()
        if response.stop_reason in ("max_tokens", "model_context_window_exceeded"):
            log.warning("Reply cut off (%s)", response.stop_reason)
            reply += "\n\n<i>(Cut off: the reply ran out of room. Try again.)</i>"
        return reply
    return "Sorry, that took too many steps. Try asking more narrowly."


def feed_params(query: str) -> dict:
    korean = re.search(r"[\uac00-\ud7a3]", query)
    hl, gl, lang = ("ko", "KR", "ko") if korean else ("en-US", "US", "en")
    return {"q": f"{query} when:1d", "hl": hl, "gl": gl, "ceid": f"{gl}:{lang}"}


async def fetch_news(categories: list[dict]) -> str:
    """Collect the last day's headlines for each category from Google News feeds (free, no key)."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=26)
    sections = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (NewsWatch bot)"}) as http:
        for c in categories:
            lines, seen = [], set()
            for query in c.get("queries") or [c["name"]]:
                try:
                    resp = await http.get(NEWS_FEED_URL, params=feed_params(query))
                    resp.raise_for_status()
                except httpx.HTTPError as e:
                    log.warning("News feed failed for %r: %s", query, e)
                    continue
                for entry in feedparser.parse(resp.content).entries[:ITEMS_PER_QUERY]:
                    published = entry.get("published_parsed")
                    if published and dt.datetime(*published[:6], tzinfo=dt.timezone.utc) < cutoff:
                        continue
                    source = entry.get("source", {}).get("title", "")
                    title = entry.get("title", "").removesuffix(f" - {source}").strip()
                    if not title or title.lower() in seen:
                        continue
                    seen.add(title.lower())
                    lines.append(f"- {title} ({source or 'unknown source'}) {entry.get('link', '')}")
            log.info("News feeds: %d headlines for %s", len(lines), c["name"])
            sections.append(f"{c['name']}:\n" + ("\n".join(lines) or "(no headlines found)"))
    return "\n\n".join(sections)


async def build_digest(state: dict) -> str:
    prompt = DIGEST_PROMPT.format(
        profile=PROFILE,
        categories=format_categories(state["categories"]),
        news=await fetch_news(state["categories"]),
        date=today(),
        format_rules=FORMAT_RULES,
    )
    return await run_claude(
        system="You write a concise, accurate daily news digest.",
        messages=[{"role": "user", "content": prompt}],
        tools=[],
        effort="medium",  # "high" spent the whole output budget on reasoning
        state=state,
    )


# ---------- Telegram ----------

def split_message(text: str, limit: int = 4000) -> list[str]:
    """Split on blank lines / newlines so each chunk fits Telegram's 4096-char limit."""
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit and current:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current)
    return chunks


async def send(bot, chat_id: int, text: str) -> None:
    for chunk in split_message(text):
        try:
            await bot.send_message(chat_id, chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception as e:  # malformed HTML: fall back to plain text with the links spelled out
            log.warning("HTML send failed (%s); sending plain text", e)
            plain = re.sub(r'<a href="([^"]+)">([^<]*)</a>', r"\2: \1", chunk)
            plain = html.unescape(re.sub(r"<[^>]+>", "", plain))
            await bot.send_message(chat_id, plain, disable_web_page_preview=True)


def allowed(update: Update) -> bool:
    return update.effective_chat is not None and update.effective_chat.id == ALLOWED_CHAT_ID


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not allowed(update):
        await update.message.reply_text(
            f"Your chat ID is {chat_id}. Set TELEGRAM_CHAT_ID={chat_id} and restart the bot."
        )
        return
    await update.message.reply_text(
        "News Watch is on. Your digest arrives weekdays at 7:45am.\n\n"
        "Just text me, e.g. \"more on 3\", \"add a category for crypto regulation\", "
        "\"what's new with the EU AI Act?\"\n\n"
        "/digest – send a digest now\n/categories – show your categories\n/reset – clear chat memory"
    )


async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    state = load_state()
    await update.message.reply_text(format_categories(state["categories"]))


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    state = load_state()
    state["history"] = []
    save_state(state)
    await update.message.reply_text("Chat memory cleared. Categories are unchanged.")


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    await update.message.reply_text("Searching today's news… this takes a few minutes.")
    await send_digest(context)


async def send_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    state = load_state()
    try:
        digest = await build_digest(state)
    except Exception as e:
        log.exception("digest failed")
        await context.bot.send_message(ALLOWED_CHAT_ID, f"Digest failed: {e}")
        return
    state["last_digest"] = digest
    # New digest = new conversation topic; keep chat memory short.
    state["history"] = []
    save_state(state)
    await send(context.bot, ALLOWED_CHAT_ID, digest)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    state = load_state()
    await context.bot.send_chat_action(ALLOWED_CHAT_ID, "typing")

    system = CHAT_SYSTEM.format(
        profile=PROFILE,
        date=today(),
        categories=format_categories(state["categories"]),
        last_digest=state["last_digest"] or "(no digest sent yet)",
        format_rules=FORMAT_RULES,
    )
    messages = state["history"] + [{"role": "user", "content": update.message.text}]
    try:
        reply = await run_claude(system, messages, [CHAT_SEARCH_TOOL, UPDATE_CATEGORIES_TOOL], "low", state)
    except Exception as e:
        log.exception("chat failed")
        await update.message.reply_text(f"Something went wrong: {e}")
        return

    reply = reply or "Done."
    state["history"] = (messages + [{"role": "assistant", "content": reply}])[-HISTORY_LIMIT:]
    # History must start with a user turn.
    while state["history"] and state["history"][0]["role"] != "user":
        state["history"].pop(0)
    save_state(state)
    await send(context.bot, ALLOWED_CHAT_ID, reply)


def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    if ALLOWED_CHAT_ID:
        app.job_queue.run_daily(send_digest, time=DIGEST_TIME, days=DIGEST_DAYS, name="daily-digest")
        log.info("Weekday digest scheduled at %s %s", DIGEST_TIME.strftime("%H:%M"), TZ)
    else:
        log.info("TELEGRAM_CHAT_ID not set: send /start to the bot to get your chat ID.")
    app.run_polling()


if __name__ == "__main__":
    main()
