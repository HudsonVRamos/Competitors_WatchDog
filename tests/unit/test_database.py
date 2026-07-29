"""Testes unitários para o módulo de database."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, AsyncEngine


class TestDatabaseModule:
    """Testes para verificar que o módulo database está corretamente configurado."""

    def test_engine_is_async(self):
        """Engine deve ser do tipo AsyncEngine."""
        from price_watchdog.database import engine

        assert isinstance(engine, AsyncEngine)

    def test_engine_url_uses_asyncpg(self):
        """Engine deve usar driver asyncpg."""
        from price_watchdog.database import engine

        assert "asyncpg" in str(engine.url)

    def test_session_factory_exists(self):
        """Session factory deve ser async_sessionmaker."""
        from price_watchdog.database import async_session_factory

        assert isinstance(async_session_factory, async_sessionmaker)

    def test_get_session_is_context_manager(self):
        """get_session deve ser um async context manager."""
        from price_watchdog.database import get_session

        import inspect
        # Verifica que é uma função decorada com asynccontextmanager
        result = get_session()
        assert hasattr(result, "__aenter__")
        assert hasattr(result, "__aexit__")
