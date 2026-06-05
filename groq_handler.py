"""
Groq handler — extract structured transaction data from natural language.
Groq picks the closest matching category from a fixed list.
"""

import os
import json
import logging
from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Category lists — edit these to customise your categories
# ─────────────────────────────────────────────────────────────────────────────

EXPENSE_CATEGORIES = [
    "Rent",
    "Home Loan / Mortgage",
    "Electricity Bill",
    "Water Bill",
    "Gas Cylinder / Gas Bill",
    "Internet / Wi-Fi",
    "Mobile Recharge",
    "Groceries",
    "Vegetables & Fruits",
    "Milk & Dairy",
    "Eating Out / Restaurants",
    "Fast Food",
    "Tea / Coffee",
    "Snacks",
    "Fuel / Petrol",
    "Public Transport",
    "Cab / Taxi",
    "Vehicle Maintenance",
    "Car Insurance",
    "Bike Insurance",
    "Medical Bills",
    "Medicines",
    "Health Insurance",
    "Gym Membership",
    "Sports Expenses",
    "School Fees",
    "College Fees",
    "Online Courses",
    "Books & Stationery",
    "Clothing",
    "Shoes & Footwear",
    "Personal Care",
    "Haircut / Salon",
    "Cosmetics",
    "Entertainment",
    "OTT Subscriptions",
    "Movie Tickets",
    "Gaming",
    "Travel",
    "Hotel Stay",
    "Gifts",
    "Donations / Charity",
    "Festivals & Celebrations",
    "EMI Payments",
    "Credit Card Bill",
    "Taxes",
    "Household Items",
    "Furniture",
    "Electronics Repair",
    "Other",
]

INCOME_CATEGORIES = [
    "Salary",
    "Freelancing",
    "Business Income",
    "Side Hustle",
    "Bonus",
    "Overtime Pay",
    "Commission",
    "Incentives",
    "Tips",
    "Rental Income",
    "Interest from Bank",
    "Fixed Deposit Interest",
    "Dividends",
    "Stock Market Profit",
    "Mutual Fund Returns",
    "Cryptocurrency Profit",
    "Pension",
    "Scholarship",
    "Stipend",
    "Cashback Rewards",
    "Refunds",
    "Gift Received",
    "Pocket Money",
    "Allowance",
    "Royalties",
    "Affiliate Marketing",
    "YouTube Revenue",
    "Blogging Income",
    "Ad Revenue",
    "Online Course Sales",
    "E-book Sales",
    "Consulting Income",
    "Coaching / Tuition",
    "Farming Income",
    "Livestock Sales",
    "Reselling Profit",
    "Cashback from Credit Card",
    "Lottery Winnings",
    "Insurance Claim",
    "Government Benefits",
    "Tax Refund",
    "Crowdfunding Received",
    "Sponsorship Income",
    "Event Earnings",
    "Photography Income",
    "App Revenue",
    "Software Sales",
    "Donation Received",
    "Profit Sharing",
]

# ─────────────────────────────────────────────────────────────────────────────
# Prompt builder
# ─────────────────────────────────────────────────────────────────────────────

_EXPENSE_LIST = "\n".join(f"  - {c}" for c in EXPENSE_CATEGORIES)
_INCOME_LIST  = "\n".join(f"  - {c}" for c in INCOME_CATEGORIES)

SYSTEM_PROMPT = f"""You are a financial transaction parser. The user will send a message in English or Hindi (or a mix) describing a financial transaction.

Your job:
1. Determine if it is an "expense" or "income".
2. Extract the amount (numeric only, no currency symbols).
3. Pick the SINGLE best matching category from the relevant list below.
4. Write a short clean note summarising the transaction.

EXPENSE categories (use one of these exactly if type is expense):
{_EXPENSE_LIST}

INCOME categories (use one of these exactly if type is income):
{_INCOME_LIST}

Rules:
- Always pick the CLOSEST matching category from the list. Never invent a new category.
- If nothing fits even loosely, use "Other" for expense or "Business Income" for income.
- Amount must be a plain number (e.g. 500, 1200.50). No commas, no symbols.
- If no amount is mentioned, return null for amount.
- Note should be concise (max 10 words), in English.
- If the message is not a financial transaction at all, return null.

Respond ONLY with a valid JSON object in this exact format (no markdown, no explanation):
{{"type": "expense" or "income", "category": "<exact category name>", "amount": <number or null>, "note": "<short note>"}}
"""

# ─────────────────────────────────────────────────────────────────────────────
# Groq client
# ─────────────────────────────────────────────────────────────────────────────

_client: AsyncGroq | None = None

def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        token = os.getenv("GROQ_API_KEY")
        if not token:
            raise ValueError("GROQ_API_KEY not set.")
        _client = AsyncGroq(api_key=token)
    return _client


# ─────────────────────────────────────────────────────────────────────────────
# Category validator — ensure Groq's response matches your list exactly
# ─────────────────────────────────────────────────────────────────────────────

def _validate_category(txn_type: str, category: str) -> str:
    """
    If Groq returns a category not in the list (hallucination),
    fall back to the closest match by checking if any list item
    contains the returned string or vice versa.
    Falls back to 'Other' / 'Business Income' if nothing matches.
    """
    cat_lower = category.strip().lower()
    candidates = EXPENSE_CATEGORIES if txn_type == "expense" else INCOME_CATEGORIES

    # Exact match (case-insensitive)
    for c in candidates:
        if c.lower() == cat_lower:
            return c

    # Partial match — candidate contains returned string or vice versa
    for c in candidates:
        if cat_lower in c.lower() or c.lower() in cat_lower:
            return c

    # Fallback
    logger.warning(f"Category '{category}' not in list for type '{txn_type}', using fallback.")
    return "Other" if txn_type == "expense" else "Business Income"


# ─────────────────────────────────────────────────────────────────────────────
# Public function
# ─────────────────────────────────────────────────────────────────────────────

GOAL_DETECT_PROMPT = """You are a financial assistant. The user will send a message in English or Hindi (or a mix).

Your job: Decide if the message is about saving money toward a goal (like "saved 2000 for trip", "goal mein 500 daala", "putting 1000 aside for goa").

If YES — return JSON with the amount saved. Example:
{"is_goal_deposit": true, "amount": 2000}

If NO (it's a regular expense/income, or unrelated) — return:
{"is_goal_deposit": false, "amount": null}

Rules:
- Amount must be a plain number. No symbols.
- If no amount is mentioned, return null for amount.
- Respond ONLY with valid JSON. No markdown, no explanation.
"""


async def detect_goal_deposit(text: str) -> dict | None:
    """
    Check if the message is a goal saving intent.
    Returns {"is_goal_deposit": True, "amount": float} or
            {"is_goal_deposit": False, "amount": None}
    Returns None on API error.
    """
    client = _get_client()

    try:
        response = await client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            messages=[
                {"role": "system", "content": GOAL_DETECT_PROMPT},
                {"role": "user",   "content": text},
            ],
            temperature=0.1,
            max_tokens=60,
        )

        raw = response.choices[0].message.content.strip()
        logger.debug(f"Groq goal detect response: {raw}")

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)
        return data

    except json.JSONDecodeError as e:
        logger.error(f"Goal detect JSON parse error: {e} | raw: {raw!r}")
        return None
    except Exception as e:
        logger.error(f"Goal detect API error: {e}")
        return None


async def extract_transaction(text: str) -> dict | None:
    """
    Parse a natural-language transaction message.
    Returns a dict with keys: type, category, amount, note
    Returns None if the message is not a transaction.
    """
    client = _get_client()

    try:
        response = await client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": text},
            ],
            temperature=0.1,      # low temperature = more deterministic category picks
            max_tokens=150,
        )

        raw = response.choices[0].message.content.strip()
        logger.debug(f"Groq raw response: {raw}")

        # Strip accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)

        # Return None if Groq signals not-a-transaction
        if data is None or data.get("amount") is None:
            return None

        txn_type = str(data.get("type", "expense")).strip().lower()
        if txn_type not in ("expense", "income"):
            txn_type = "expense"

        # Validate & correct category
        raw_category = str(data.get("category", "Other"))
        category = _validate_category(txn_type, raw_category)

        # Safely parse amount
        try:
            amount = float(str(data.get("amount", 0)).replace(",", "").strip())
        except (ValueError, TypeError):
            amount = 0.0

        return {
            "type":     txn_type,
            "category": category,
            "amount":   amount,
            "note":     str(data.get("note", text))[:100],
        }

    except json.JSONDecodeError as e:
        logger.error(f"Groq JSON parse error: {e} | raw: {raw!r}")
        return None
    except Exception as e:
        logger.error(f"Groq API error: {e}")
        raise
