"""Shared pytest fixtures."""

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import create_app


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Create and drop test database tables once per session."""
    asyncio.run(_create_tables())
    yield
    asyncio.run(_drop_tables())


async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _drop_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def client():
    """Yield a FastAPI TestClient with lifespan support."""
    app = create_app()
    with TestClient(app) as c:
        yield c
