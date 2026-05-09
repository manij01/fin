"""Tests for the POST /api/chat endpoint in mock mode."""

import os

os.environ["LLM_MOCK"] = "true"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.database as database
from app.chat import _coerce_chat_response
from app.main import app
from app.market.cache import price_cache


@pytest.fixture(autouse=True)
def seed_prices():
    """Seed current prices so AI trades use the same path as manual trades."""
    price_cache.update("AAPL", 150.0)
    price_cache.update("GOOGL", 175.0)
    price_cache.update("MSFT", 420.0)
    price_cache.update("AMZN", 185.0)
    price_cache.update("TSLA", 250.0)
    price_cache.update("NVDA", 120.0)
    price_cache.update("META", 500.0)
    price_cache.update("JPM", 200.0)
    price_cache.update("V", 310.0)
    price_cache.update("NFLX", 650.0)
    yield
    price_cache._prices.clear()


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async test client with a fresh per-test SQLite DB."""
    db_file = str(tmp_path / "test.db")
    database.DB_PATH = db_file
    await database.init_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_chat_greeting(client):
    resp = await client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert "FinAlly" in data["message"]
    assert data["trades"] is None
    assert data["watchlist_changes"] is None


async def test_chat_buy_aapl(client):
    """Mock buy uses canonical trade execution at the cached market price."""
    resp = await client.post("/api/chat", json={"message": "buy some AAPL"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["trades"] is not None
    assert len(data["trades"]) == 1
    trade = data["trades"][0]
    assert trade["ticker"] == "AAPL"
    assert trade["side"] == "buy"
    assert trade["quantity"] == 10
    # No errors appended
    assert "Errors" not in data["message"]

    resp = await client.get("/api/portfolio")
    portfolio = resp.json()
    assert portfolio["cash_balance"] == 10000.0 - (10 * 150.0)
    assert portfolio["positions"][0]["ticker"] == "AAPL"
    assert portfolio["positions"][0]["quantity"] == 10
    assert portfolio["positions"][0]["avg_cost"] == 150.0

    resp = await client.get("/api/portfolio/history")
    assert len(resp.json()) == 1


async def test_chat_sell_insufficient(client):
    """Selling without owning shares should report error in message."""
    resp = await client.post("/api/chat", json={"message": "sell some AAPL"})
    assert resp.status_code == 200
    data = resp.json()
    # Upstream appends errors to message
    assert "Insufficient" in data["message"] or "Errors" in data["message"]
    assert data["trades"] is None


async def test_chat_buy_then_sell(client):
    """Buy then sell should use the latest cached market price."""
    # Buy first (10 shares at $250 = $2500)
    resp = await client.post("/api/chat", json={"message": "buy some TSLA"})
    data = resp.json()
    assert data["trades"][0]["ticker"] == "TSLA"
    assert "Errors" not in data["message"]

    # Sell at the latest market price, not avg cost.
    price_cache.update("TSLA", 300.0)
    resp = await client.post("/api/chat", json={"message": "sell some TSLA"})
    data = resp.json()
    assert "Insufficient" not in data["message"]

    resp = await client.get("/api/portfolio")
    portfolio = resp.json()
    assert portfolio["cash_balance"] == 10500.0
    assert portfolio["positions"] == []


async def test_chat_buy_insufficient_cash(client):
    """Buying more than cash allows should fail. 10 * $150 = $1500, so
    need to exhaust cash first."""
    # Buy 7 times: 7 * 10 * $150 = $10,500 > $10,000
    # First 6 buys: 6 * $1500 = $9000 (leaving $1000)
    for _ in range(6):
        await client.post("/api/chat", json={"message": "buy some AAPL"})

    # 7th buy: $1500 > $1000 remaining
    resp = await client.post("/api/chat", json={"message": "buy some AAPL"})
    data = resp.json()
    assert "Insufficient" in data["message"]


async def test_chat_watchlist_add(client):
    resp = await client.post("/api/chat", json={"message": "add PYPL to watchlist"})
    data = resp.json()
    assert data["watchlist_changes"] is not None
    assert data["watchlist_changes"][0]["ticker"] == "PYPL"
    assert data["watchlist_changes"][0]["action"] == "add"

    watchlist = (await client.get("/api/watchlist")).json()
    assert "PYPL" in {item["ticker"] for item in watchlist}

    resp = await client.post("/api/chat", json={"message": "add PYPL to watchlist"})
    data = resp.json()
    assert data["watchlist_changes"] is None
    assert "already on the watchlist" in data["message"]


async def test_chat_watchlist_remove(client):
    resp = await client.post("/api/chat", json={"message": "remove NFLX"})
    data = resp.json()
    assert data["watchlist_changes"] is not None
    assert data["watchlist_changes"][0]["ticker"] == "NFLX"
    assert data["watchlist_changes"][0]["action"] == "remove"


async def test_chat_portfolio_query(client):
    resp = await client.post("/api/chat", json={"message": "show my portfolio"})
    data = resp.json()
    assert "portfolio" in data["message"].lower()
    assert data["trades"] is None


async def test_chat_fallback(client):
    resp = await client.post("/api/chat", json={"message": "random nonsense xyz"})
    data = resp.json()
    assert "trade" in data["message"].lower() or "portfolio" in data["message"].lower()


async def test_chat_persists_history_actions_and_errors(client):
    await client.post("/api/chat", json={"message": "sell some AAPL"})

    db = await database.get_db()
    try:
        cursor = await db.execute(
            "SELECT role, content, actions FROM chat_messages ORDER BY created_at"
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert "Insufficient shares" in rows[1]["content"]
    assert "Insufficient shares" in rows[1]["actions"]


def test_coerce_chat_response_ignores_invalid_actions():
    response = _coerce_chat_response(
        {
            "message": "Done.",
            "trades": [{"ticker": "AAPL", "side": "hold", "quantity": 1}],
            "watchlist_changes": [{"ticker": "", "action": "add"}],
        }
    )

    assert response.trades is None
    assert response.watchlist_changes is None
    assert "Ignored invalid trade action" in response.message
    assert "Ignored invalid watchlist action" in response.message
