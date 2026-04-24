"""Smoke tests for the price-scraper arq wiring.

Confirms:
  * `scrape_prices_job` forwards `slug` into the registry + runner.
  * `scrape_all_prices_job` fans out one enqueue per registered slug.
  * Both jobs are present in `WorkerSettings.functions`.
  * The monthly cron is present in `WorkerSettings.cron_jobs`.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

asyncio_test = pytest.mark.asyncio


# ---------- scrape_prices_job forwarding ----------


@asyncio_test
async def test_scrape_prices_job_calls_run_scraper_with_instance(monkeypatch):
    from services import price_scrapers
    from workers import queue

    fake_instance = object()
    fake_run = AsyncMock(return_value={"ok": True, "slug": "hanoi"})
    monkeypatch.setattr(price_scrapers, "get_scraper", MagicMock(return_value=fake_instance))
    monkeypatch.setattr(price_scrapers, "run_scraper", fake_run)

    result = await queue.scrape_prices_job(ctx={}, slug="hanoi")

    assert result == {"ok": True, "slug": "hanoi"}
    fake_run.assert_awaited_once_with(fake_instance)


# ---------- Fan-out ----------


@asyncio_test
async def test_scrape_all_prices_job_enqueues_one_per_slug(monkeypatch):
    from services import price_scrapers
    from workers import queue

    # Freeze the slug list so the test doesn't care about the real 64-slug count.
    monkeypatch.setattr(price_scrapers, "all_slugs", lambda: ["moc", "hanoi", "hcmc"])

    pool = MagicMock()
    pool.enqueue_job = AsyncMock()
    monkeypatch.setattr(queue, "get_pool", AsyncMock(return_value=pool))

    out = await queue.scrape_all_prices_job(ctx={})

    assert out == {"enqueued": ["moc", "hanoi", "hcmc"]}
    assert pool.enqueue_job.await_count == 3
    for (args, _kw), expected_slug in zip(
        pool.enqueue_job.await_args_list, ["moc", "hanoi", "hcmc"]
    ):
        name, slug = args
        assert name == "scrape_prices_job"
        assert slug == expected_slug


# ---------- Worker registration ----------


def test_worker_settings_registers_scraper_jobs():
    from workers.queue import (
        WorkerSettings,
        scrape_all_prices_job,
        scrape_prices_job,
    )

    assert scrape_prices_job in WorkerSettings.functions
    assert scrape_all_prices_job in WorkerSettings.functions


def test_worker_settings_registers_monthly_cron():
    from workers.queue import WorkerSettings, scrape_all_prices_job

    # arq.cron.CronJob exposes the underlying coroutine as `.coroutine` in
    # recent versions; older ones stash it on `.func`. Accept either.
    crons = WorkerSettings.cron_jobs
    targets = [
        getattr(c, "coroutine", None) or getattr(c, "func", None)
        for c in crons
    ]
    assert scrape_all_prices_job in targets
