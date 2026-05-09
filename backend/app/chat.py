"""POST /api/chat — LLM chat with auto-execution of trades and watchlist changes."""

import json
import os
import uuid
from datetime import datetime, timezone
from json import JSONDecodeError
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field, ValidationError, field_validator

from litellm import acompletion

from app.database import get_db
from app.portfolio import TradeExecutionError, execute_trade_for_user
from app.tickers import normalize_ticker

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str


class TradeAction(BaseModel):
    ticker: str
    side: str
    quantity: float = Field(gt=0)

    @field_validator("ticker")
    @classmethod
    def normalize_trade_ticker(cls, value: str) -> str:
        return normalize_ticker(value)

    @field_validator("side")
    @classmethod
    def normalize_side(cls, value: str) -> str:
        side = value.lower().strip()
        if side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        return side


class WatchlistChange(BaseModel):
    ticker: str
    action: str  # "add" | "remove"

    @field_validator("ticker")
    @classmethod
    def normalize_watchlist_ticker(cls, value: str) -> str:
        return normalize_ticker(value)

    @field_validator("action")
    @classmethod
    def normalize_action(cls, value: str) -> str:
        action = value.lower().strip()
        if action not in ("add", "remove"):
            raise ValueError("action must be 'add' or 'remove'")
        return action


class ChatResponse(BaseModel):
    message: str
    trades: list[TradeAction] | None = None
    watchlist_changes: list[WatchlistChange] | None = None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are FinAlly, an AI trading assistant inside a simulated trading workstation.

Your capabilities:
- Analyze the user's portfolio composition, risk concentration, and P&L
- Suggest trades with clear reasoning
- Execute trades when the user asks or agrees (by including them in your response)
- Manage the watchlist (add/remove tickers)
- Be concise and data-driven

You MUST respond with valid JSON matching this schema:
{
  "message": "Your conversational response to the user",
  "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10}],
  "watchlist_changes": [{"ticker": "PYPL", "action": "add"}]
}

Rules:
- "message" is always required.
- "trades" is optional — include only when executing trades.
- "watchlist_changes" is optional — include only when modifying the watchlist.
- side must be "buy" or "sell". action must be "add" or "remove".
- Only execute trades when the user explicitly asks or agrees.
- Keep responses concise."""


# ---------------------------------------------------------------------------
# Portfolio context
# ---------------------------------------------------------------------------


async def _load_portfolio_context(db) -> str:
    """Build a text summary of the user's portfolio for the LLM."""
    # Cash balance
    cur = await db.execute(
        "SELECT cash_balance FROM users_profile WHERE id = 'default'"
    )
    row = await cur.fetchone()
    cash = row["cash_balance"] if row else 10000.0

    # Positions
    cur = await db.execute(
        "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id = 'default'"
    )
    positions = await cur.fetchall()

    # Watchlist
    cur = await db.execute(
        "SELECT ticker FROM watchlist WHERE user_id = 'default'"
    )
    watchlist = [r["ticker"] for r in await cur.fetchall()]

    lines = [f"Cash: ${cash:,.2f}"]

    if positions:
        lines.append("Positions:")
        total_cost = 0.0
        for p in positions:
            value = p["quantity"] * p["avg_cost"]
            total_cost += value
            lines.append(
                f"  {p['ticker']}: {p['quantity']} shares @ avg ${p['avg_cost']:.2f}"
            )
        lines.append(f"Total invested (at cost): ${total_cost:,.2f}")
    else:
        lines.append("Positions: none")

    lines.append(f"Watchlist: {', '.join(watchlist) if watchlist else 'empty'}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------


async def _load_history(db, limit: int = 20) -> list[dict]:
    """Load recent chat messages for context."""
    cur = await db.execute(
        "SELECT role, content FROM chat_messages "
        "WHERE user_id = 'default' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    rows = await cur.fetchall()
    # Reverse so oldest first
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# ---------------------------------------------------------------------------
# Mock mode
# ---------------------------------------------------------------------------


def _mock_response(message: str) -> ChatResponse:
    """Return deterministic mock responses for testing."""
    lower = message.lower()

    if any(w in lower for w in ["hi", "hello", "hey"]):
        return ChatResponse(
            message="Hello! I'm FinAlly, your AI trading assistant. "
            "I can analyze your portfolio, suggest trades, and manage your watchlist. "
            "How can I help you today?"
        )

    if "portfolio" in lower or "positions" in lower or "holdings" in lower:
        return ChatResponse(
            message="Your portfolio currently has $10,000.00 in cash with no open positions. "
            "You're watching AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX. "
            "Would you like to make a trade?"
        )

    if "buy" in lower:
        # Extract ticker if mentioned
        ticker = "AAPL"
        for t in ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]:
            if t.lower() in lower:
                ticker = t
                break
        return ChatResponse(
            message=f"Buying 10 shares of {ticker} for you.",
            trades=[TradeAction(ticker=ticker, side="buy", quantity=10)],
        )

    if "sell" in lower:
        ticker = "AAPL"
        for t in ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]:
            if t.lower() in lower:
                ticker = t
                break
        return ChatResponse(
            message=f"Selling 10 shares of {ticker} for you.",
            trades=[TradeAction(ticker=ticker, side="sell", quantity=10)],
        )

    if "watch" in lower or "add" in lower:
        return ChatResponse(
            message="Adding PYPL to your watchlist.",
            watchlist_changes=[WatchlistChange(ticker="PYPL", action="add")],
        )

    if "remove" in lower:
        return ChatResponse(
            message="Removing NFLX from your watchlist.",
            watchlist_changes=[WatchlistChange(ticker="NFLX", action="remove")],
        )

    return ChatResponse(
        message="I can help you trade, analyze your portfolio, or manage your watchlist. "
        "What would you like to do?"
    )


# ---------------------------------------------------------------------------
# Watchlist changes
# ---------------------------------------------------------------------------


async def _execute_watchlist_change(db, ticker: str, action: str) -> str | None:
    """Add/remove a ticker from watchlist. Returns error string on failure."""
    try:
        ticker = normalize_ticker(ticker)
    except ValueError as exc:
        return str(exc)

    action = action.lower().strip()
    now = datetime.now(timezone.utc).isoformat()

    if action == "add":
        cur = await db.execute(
            "SELECT id FROM watchlist WHERE user_id = 'default' AND ticker = ?",
            (ticker,),
        )
        if await cur.fetchone():
            return f"{ticker} is already on the watchlist"
        await db.execute(
            "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, 'default', ?, ?)",
            (str(uuid.uuid4()), ticker, now),
        )

    elif action == "remove":
        cur = await db.execute(
            "DELETE FROM watchlist WHERE user_id = 'default' AND ticker = ?",
            (ticker,),
        )
        if cur.rowcount == 0:
            return f"{ticker} is not on the watchlist"
    else:
        return f"Invalid watchlist action: {action}"

    return None


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def _format_validation_error(error: ValidationError) -> str:
    """Convert pydantic validation failures into compact chat-visible text."""
    details = []
    for err in error.errors():
        field = ".".join(str(part) for part in err["loc"])
        details.append(f"{field}: {err['msg']}")
    return "; ".join(details)


def _coerce_chat_response(payload: dict[str, Any]) -> ChatResponse:
    """Parse LLM JSON while ignoring invalid action items individually."""
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        message = "I could not parse a usable assistant message."

    errors: list[str] = []
    trades: list[TradeAction] = []
    for raw_trade in payload.get("trades") or []:
        try:
            trades.append(TradeAction.model_validate(raw_trade))
        except ValidationError as exc:
            errors.append(f"Ignored invalid trade action ({_format_validation_error(exc)})")

    watchlist_changes: list[WatchlistChange] = []
    for raw_change in payload.get("watchlist_changes") or []:
        try:
            watchlist_changes.append(WatchlistChange.model_validate(raw_change))
        except ValidationError as exc:
            errors.append(
                f"Ignored invalid watchlist action ({_format_validation_error(exc)})"
            )

    if errors:
        message += "\n\n(Errors: " + "; ".join(errors) + ")"

    return ChatResponse(
        message=message,
        trades=trades or None,
        watchlist_changes=watchlist_changes or None,
    )


async def _call_llm(messages: list[dict]) -> ChatResponse:
    """Call LLM via LiteLLM -> OpenRouter and parse structured response."""
    response = await acompletion(
        model="openrouter/openai/gpt-oss-120b",
        messages=messages,
        extra_body={
            "response_format": {"type": "json_object"},
        },
    )

    content = response.choices[0].message.content
    try:
        parsed = json.loads(content) if isinstance(content, str) else content
        if not isinstance(parsed, dict):
            raise TypeError("LLM response was not a JSON object")
        return _coerce_chat_response(parsed)
    except (JSONDecodeError, TypeError, ValidationError) as exc:
        return ChatResponse(
            message=(
                "I could not parse the model response into the expected action format."
                f"\n\n(Errors: {exc})"
            )
        )


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------


@router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message and receive a structured response with auto-executed actions."""
    db = await get_db()
    try:
        # Check mock mode
        if os.environ.get("LLM_MOCK", "").lower() == "true":
            result = _mock_response(req.message)
        else:
            # Build LLM messages
            portfolio_ctx = await _load_portfolio_context(db)
            history = await _load_history(db)

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "system",
                    "content": f"Current portfolio state:\n{portfolio_ctx}",
                },
                *history,
                {"role": "user", "content": req.message},
            ]

            result = await _call_llm(messages)

        # Auto-execute trades
        errors = []
        executed_trades: list[TradeAction] = []
        if result.trades:
            for trade in result.trades:
                try:
                    executed = await execute_trade_for_user(
                        db, trade.ticker, trade.side, trade.quantity
                    )
                    executed_trades.append(
                        TradeAction(
                            ticker=executed.ticker,
                            side=executed.side,
                            quantity=executed.quantity,
                        )
                    )
                except TradeExecutionError as exc:
                    errors.append(str(exc))
        result.trades = executed_trades or None

        # Auto-execute watchlist changes
        executed_watchlist_changes: list[WatchlistChange] = []
        if result.watchlist_changes:
            for change in result.watchlist_changes:
                err = await _execute_watchlist_change(
                    db, change.ticker, change.action
                )
                if err:
                    errors.append(err)
                else:
                    executed_watchlist_changes.append(change)
        result.watchlist_changes = executed_watchlist_changes or None

        # Append errors to message if any
        if errors:
            result.message += "\n\n(Errors: " + "; ".join(errors) + ")"

        # Store messages
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
            "VALUES (?, 'default', 'user', ?, NULL, ?)",
            (str(uuid.uuid4()), req.message, now),
        )

        actions_payload = result.model_dump(exclude={"message"}, exclude_none=True)
        if errors:
            actions_payload["errors"] = errors
        actions_json = json.dumps(actions_payload) if actions_payload else None

        await db.execute(
            "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
            "VALUES (?, 'default', 'assistant', ?, ?, ?)",
            (str(uuid.uuid4()), result.message, actions_json, now),
        )
        await db.commit()

        return result
    finally:
        await db.close()
