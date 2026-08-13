"""Tests for the HTTP retry policy.

Retries matter most on Workday, which pages 20 jobs at a time -- one transient
503 partway through a 700-job tenant would otherwise lose that whole company.
"""

import httpx
import pytest

from scraper.adapters.api import RetryableStatus, request, workday


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_retries_server_error_then_succeeds():
    calls = []

    def handler(req):
        calls.append(req.url)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    async with _client(handler) as client:
        r = await request(client, "GET", "https://example.com/jobs")

    assert r.status_code == 200
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_retries_rate_limit():
    calls = []

    def handler(req):
        calls.append(req.url)
        return httpx.Response(429 if len(calls) == 1 else 200, json={})

    async with _client(handler) as client:
        r = await request(client, "GET", "https://example.com/jobs")

    assert r.status_code == 200
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_does_not_retry_client_error():
    """A 404 is a real answer -- the board moved. Repeating won't help."""
    calls = []

    def handler(req):
        calls.append(req.url)
        return httpx.Response(404)

    async with _client(handler) as client:
        r = await request(client, "GET", "https://example.com/gone")

    assert r.status_code == 404
    assert len(calls) == 1, "404 must not be retried"


@pytest.mark.asyncio
async def test_gives_up_after_three_attempts():
    calls = []

    def handler(req):
        calls.append(req.url)
        return httpx.Response(500)

    async with _client(handler) as client:
        with pytest.raises(RetryableStatus):
            await request(client, "GET", "https://example.com/broken")

    assert len(calls) == 3


@pytest.mark.asyncio
async def test_workday_paging_survives_a_transient_failure():
    """The case that motivated adding retries at all."""
    state = {"calls": 0, "failed": False}

    def handler(req):
        state["calls"] += 1
        body = req.content.decode()
        offset = 20 if '"offset": 20' in body or '"offset":20' in body else 0

        # Fail once, partway through paging.
        if offset == 20 and not state["failed"]:
            state["failed"] = True
            return httpx.Response(503)

        page = [
            {"title": f"Data Engineer {offset + i}", "externalPath": f"/job/x{offset + i}",
             "locationsText": "London"}
            for i in range(20 if offset == 0 else 5)
        ]
        return httpx.Response(200, json={"total": 25, "jobPostings": page})

    async with _client(handler) as client:
        postings = await workday(client, {"tenant": "t", "host": "wd1", "site": "s"})

    assert len(postings) == 25, "must recover and return the full tenant"
    assert state["failed"] is True
