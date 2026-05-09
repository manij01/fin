"""Tests for SSE price event generation."""

import json

import pytest

from app.market.cache import price_cache
from app.market.stream import _price_event_generator


@pytest.mark.asyncio
async def test_price_event_generator_yields_seeded_prices():
    price_cache.update("AAPL", 151.25)
    gen = _price_event_generator()
    try:
        event = await anext(gen)
    finally:
        await gen.aclose()
        price_cache._prices.clear()

    assert event["event"] == "price"
    data = json.loads(event["data"])
    assert data["ticker"] == "AAPL"
    assert data["price"] == 151.25
    assert data["direction"] == "flat"
