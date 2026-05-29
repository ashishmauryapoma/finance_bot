"""
Groq AI handler — converts natural language to structured transaction JSON
Supports English + Hindi (Hinglish) financial messages
"""

import os
import json
import logging
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM_PROMPT = """You are a financial transaction parser. Your ONLY job is to extract structured transaction data from natural language messages — including English, Hindi, and Hinglish (Hindi-English mix).

You MUST respond with ONLY a valid JSON object — no explanation, no extra text, no markdown.

JSON format:
{
  "type": "expense" | "income",
  "amount": <number>,
  "category": "<category string>",
  "note": "<short description>"
}

Categories to use (pick the closest match):
- Food & Dining
- Fuel
- Groceries
- Transport
- Utilities
- Rent
- Healthcare
- Entertainment
- Shopping
- Education
- Salary
- Freelance
- Business Income
- Investment
- Other

Rules:
1. "type" must be "expense" for spending/payments, "income" for receiving money.
2. "amount" must be a plain number (no currency symbol).
3. "category" must be one of the listed categories above.
4. "note" should be a short English summary (max 10 words).
5. If the message is NOT a financial transaction at all, respond with: {"error": "not_a_transaction"}
6. Handle Hindi numbers: ek=1, do=2, teen=3, char=4, paanch=5, das=10, bees=20, pachaas=50, sau=100, hazaar=1000, lakh=100000

Examples:
Input: "Spent 500 on petrol" → {"type":"expense","amount":500,"category":"Fuel","note":"Petrol"}
Input: "Received 50000 salary" → {"type":"income","amount":50000,"category":"Salary","note":"Monthly salary"}
Input: "1200 rupay grocery mein gaye" → {"type":"expense","amount":1200,"category":"Groceries","note":"Grocery shopping"}
Input: "Paanch sau ka khana" → {"type":"expense","amount":500,"category":"Food & Dining","note":"Food expense"}
Input: "Teen hazaar freelance mila" → {"type":"income","amount":3000,"category":"Freelance","note":"Freelance income"}
Input: "Paid 800 electricity bill" → {"type":"expense","amount":800,"category":"Utilities","note":"Electricity bill"}
Input: "Hello how are you" → {"error":"not_a_transaction"}
"""


async def extract_transaction(message: str) -> dict | None:
    """
    Send message to Groq AI and extract structured transaction data.
    Returns dict with transaction data, or None if not a valid transaction.
    """
    try:
        logger.info(f"Sending to Groq: {message}")

        response = client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            temperature=0.1,
            max_tokens=200,
        )

        raw = response.choices[0].message.content.strip()
        logger.info(f"Groq response: {raw}")

        # Clean markdown code blocks if present
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

        data = json.loads(raw)

        # Check if AI flagged it as not a transaction
        if data.get("error") == "not_a_transaction":
            logger.info("Message not identified as a transaction")
            return None

        # Validate required fields
        if not all(k in data for k in ("type", "amount", "category", "note")):
            logger.warning(f"Missing fields in Groq response: {data}")
            return None

        # Validate type
        if data["type"] not in ("expense", "income"):
            data["type"] = "expense"

        # Ensure amount is a number
        data["amount"] = float(data["amount"])

        return data

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error from Groq: {e} | Raw: {raw}")
        return None
    except Exception as e:
        logger.error(f"Groq API error: {e}")
        raise
