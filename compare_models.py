"""Compare today's digest written from articles with one written from headlines alone, and what each costs.

    python compare_models.py                      # article digest vs headline-only digest (Sonnet)
    python compare_models.py claude-haiku-5-5 ... # headline-only digests from these models instead

Both use the same headlines. Needs ANTHROPIC_API_KEY (no Telegram token) and sends nothing to Telegram,
but sites that block the article fetch are saved to state.json, as in a real digest.
Each digest is saved as digest-<name>.html next to this file to read side by side.
"""

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "unused")  # bot.py reads it on import
import bot  # noqa: E402

# $ per million tokens: (input, output). Haiku costs 5x more once a request passes 100K input tokens.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
WEEKDAYS_PER_MONTH = 22


def cost(model: str, tokens: dict) -> float | None:
    if model not in PRICES:
        return None
    price_in, price_out = PRICES[model]
    if "haiku" in model and tokens["input_tokens"] > 100_000:  # approximate: the limit is per request
        price_in, price_out = price_in * 5, price_out * 5
    return (tokens["input_tokens"] * price_in + tokens["output_tokens"] * price_out) / 1_000_000


def report(name: str, digest: str | None, usage: dict) -> None:
    if digest:
        Path(__file__).with_name(f"digest-{name}.html").write_text(digest)
    print(f"\n{name}" + ("" if digest else " (too few articles loaded: no digest)"))
    total = 0.0
    for model, tokens in usage.items():
        c = cost(model, tokens)
        total += c or 0
        price = f"${c:.4f}" if c is not None else "unknown price"
        print(f"  {model:<20} in {tokens['input_tokens']:>7}  out {tokens['output_tokens']:>6}  {price}")
    print(f"  total ${total:.4f} per digest, ${total * WEEKDAYS_PER_MONTH:.2f} per month")


async def main(models: list[str]) -> None:
    state = bot.load_state()
    news = await bot.fetch_news(state["categories"], state.get("blocked_sites", {}))
    items, headlines = bot.number_headlines(news)
    print(f"{len(items)} headlines")

    if not models:
        usage = {}
        digest = await bot.article_digest(state, items, headlines, usage)
        report("articles", digest, usage)
    for model in models or [bot.EDITOR_MODEL]:
        usage = {}
        digest = await bot.headline_digest(state, items, headlines, model=model, usage=usage)
        report(f"headlines-{model}", digest, usage)
    print("\nOutput tokens include the models' reasoning.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
