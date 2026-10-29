"""Write today's digest with several models from the same headlines, and compare cost.

    python compare_models.py                       # Haiku vs Sonnet
    python compare_models.py claude-opus-5-5 ...   # any models

Needs ANTHROPIC_API_KEY (no Telegram token). Saves each digest as digest-<model>.html
next to this file so you can read them side by side. Sends nothing to Telegram.
"""

import asyncio
import os
import re
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


def cost(model: str, usage: dict) -> float | None:
    if model not in PRICES:
        return None
    price_in, price_out = PRICES[model]
    if "haiku" in model and usage["input_tokens"] > 100_000:
        price_in, price_out = price_in * 5, price_out * 5
    return (usage["input_tokens"] * price_in + usage["output_tokens"] * price_out) / 1_000_000


async def main(models: list[str]) -> None:
    state = bot.load_state()
    prompt, links = await bot.digest_prompt(state)  # one fetch, so every model sees the same headlines
    print(f"{len(links)} headlines\n")
    rows = []
    for model in models:
        usage = {}
        digest = await bot.write_digest(prompt, links, state, model=model, usage=usage)
        Path(__file__).with_name(f"digest-{model}.html").write_text(digest)
        stories = len(re.findall(r'<a href="(?!item:)[^"]+">', digest))
        rows.append((model, usage, stories, cost(model, usage)))

    print(f"{'model':<20} {'input':>8} {'output':>8} {'stories':>8} {'$/digest':>9} {'$/month':>8}")
    for model, usage, stories, c in rows:
        price = f"{c:9.4f} {c * WEEKDAYS_PER_MONTH:8.2f}" if c is not None else f"{'?':>9} {'?':>8}"
        print(f"{model:<20} {usage['input_tokens']:>8} {usage['output_tokens']:>8} {stories:>8} {price}")
    print("\nDigests saved as digest-<model>.html. Output tokens include the model's reasoning.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["claude-haiku-5-5", "claude-sonnet-5-5"]))
