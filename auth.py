"""
Authentication module
Handles password verification and session management
Sessions are stored in-memory (persist while bot is running)
For persistent sessions across restarts, use a database or file
"""

import os
import hashlib
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# In-memory session store: { user_id: bool }
_sessions: dict[str, bool] = {}


def _hash_password(password: str) -> str:
    """Return SHA-256 hash of the password."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(entered: str) -> bool:
    """
    Verify the entered password against the stored hash or plaintext.
    Supports both SHA-256 hashed and plaintext BOT_PASSWORD env vars.
    """
    stored = os.getenv("BOT_PASSWORD", "")
    if not stored:
        logger.warning("BOT_PASSWORD not set — all passwords rejected.")
        return False

    # Compare plaintext directly
    if entered == stored:
        return True

    # Compare SHA-256 hash (if stored as hash)
    if _hash_password(entered) == stored:
        return True

    return False


def is_authenticated(user_id: str) -> bool:
    """Check if a user is currently authenticated."""
    return _sessions.get(str(user_id), False)


def set_authenticated(user_id: str, status: bool):
    """Set authentication status for a user."""
    _sessions[str(user_id)] = status
    action = "authenticated" if status else "logged out"
    logger.info(f"User {user_id} {action}")


def get_all_sessions() -> dict:
    """Return all active sessions (for debugging)."""
    return dict(_sessions)
