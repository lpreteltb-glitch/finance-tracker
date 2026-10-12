import logging
import re
from typing import Literal

import anthropic
from pydantic import BaseModel

# Checked in order, first match wins, so specific keywords ("UBER EATS") come before broad ones ("UBER").
RULES = {
    "Income": ["PAYROLL", "DIRECT DEP"],
    "Groceries": ["TRADER JOE", "WHOLE FOODS", "SAFEWAY", "KROGER", "ALDI", "COSTCO", "PUBLIX"],
    "Dining": ["UBER EATS", "DOORDASH", "GRUBHUB", "STARBUCKS", "CHIPOTLE", "MCDONALD", "COFFEE", "PIZZA", "CAFE"],
    "Transport": ["UBER", "LYFT", "PARKING"],
    "Utilities": ["COMCAST", "VERIZON", "T-MOBILE", "AT&T", "ELECTRIC"],
    "Gas": ["SHELL", "CHEVRON", "EXXON"],
    "Subscriptions": ["NETFLIX", "SPOTIFY", "HULU", "DISNEY", "YOUTUBE"],
    "Shopping": ["AMAZON", "TARGET", "WALMART", "BEST BUY"],
    "Health": ["CVS", "WALGREENS", "PHARMACY", "FITNESS", "GYM", "DENTAL", "MEDICAL"],
    "Travel": ["AIRLINE", "AIR LINES", "AIRBNB", "HOTEL", "MARRIOTT", "HILTON", "EXPEDIA"],
}
CATEGORIES = [*RULES, "Rent", "Entertainment", "Transfer", "Other"]

log = logging.getLogger(__name__)


def merchant_key(description):
    """'STARBUCKS STORE 1234' -> 'STARBUCKS STORE', so corrections apply to every visit to that merchant."""
    words = re.sub(r"[^A-Z& ]", " ", description.upper()).split()
    return " ".join(words[:3])


def rule_category(description):
    desc = description.upper()
    return next((cat for cat, kws in RULES.items() if any(kw in desc for kw in kws)), None)


class Labeled(BaseModel):
    merchant: str
    category: Literal[tuple(CATEGORIES)]


class Labels(BaseModel):
    labels: list[Labeled]


def ai_categories(merchants):
    """Ask Claude to label merchants the rules missed. Returns {merchant: category}; {} if unavailable."""
    if not merchants:
        return {}
    try:
        response = anthropic.Anthropic().beta.messages.parse(
            model="claude-opus-5-5",
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low"},
            output_format=Labels,
            messages=[{
                "role": "user",
                "content": "Categorize each merchant from a bank statement into one spending category. "
                "Use Other only if nothing fits.\n\n" + "\n".join(merchants),
            }],
        )
    # TypeError is what the SDK raises when no API key is configured; categorization is best-effort.
    except (anthropic.AnthropicError, TypeError) as e:
        log.warning("AI categorization skipped: %s", e)
        return {}
    if response.stop_reason == "refusal" or response.parsed_output is None:
        log.warning("AI categorization returned no labels (stop_reason=%s)", response.stop_reason)
        return {}
    return {l.merchant: l.category for l in response.parsed_output.labels if l.merchant in merchants}
