"""Проверка соответствия базы последней миграции приложения."""

from functools import lru_cache
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine


@lru_cache(maxsize=1)
def migration_heads() -> frozenset[str]:
    """Получить ожидаемые heads из поставляемого каталога миграций."""

    project_root = Path(__file__).resolve().parent.parent
    config = AlembicConfig(str(project_root / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


def database_is_current(engine: Engine) -> bool:
    """Проверить, что база помечена всеми актуальными heads Alembic."""

    with engine.connect() as connection:
        current_heads = frozenset(
            MigrationContext.configure(connection).get_current_heads()
        )
    return current_heads == migration_heads()
