"""Tests for app.db.migrate module."""

import tempfile
from pathlib import Path
from typing import AsyncGenerator, Generator

import aiosqlite
import pytest

from app.db.migrate import MigrationError, MigrationManager


class TestMigrationManager:
    """Test MigrationManager functionality."""

    @pytest.fixture
    def temp_db_path(self) -> Path:
        """Create a temporary database path."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            return Path(f.name)

    @pytest.fixture
    def temp_migrations_dir(self) -> Generator[Path, None, None]:
        """Create a temporary migrations directory."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        # Cleanup - remove all files in temp dir
        for file in temp_dir.glob("*"):
            file.unlink()
        temp_dir.rmdir()

    @pytest.fixture
    async def migration_manager(self, temp_db_path: Path, temp_migrations_dir: Path) -> AsyncGenerator[MigrationManager, None]:
        """Create a MigrationManager instance with isolated temp dirs."""
        manager = MigrationManager(temp_db_path)
        # Override the migrations directory to use our temp dir
        manager.migrations_dir = temp_migrations_dir
        yield manager
        # Cleanup
        if temp_db_path.exists():
            temp_db_path.unlink()

    async def test_init_creates_schema_migrations_table(
        self, migration_manager: MigrationManager
    ) -> None:
        """Test that initialization creates the schema_migrations table."""
        await migration_manager.init()

        async with aiosqlite.connect(migration_manager.db_path) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            )
            result = await cursor.fetchone()
            assert result is not None
            assert result[0] == "schema_migrations"

    async def test_get_applied_migrations_empty(
        self, migration_manager: MigrationManager
    ) -> None:
        """Test getting applied migrations when none exist."""
        await migration_manager.init()
        applied = await migration_manager.get_applied_migrations()
        assert applied == set()

    async def test_get_applied_migrations_with_data(
        self, migration_manager: MigrationManager
    ) -> None:
        """Test getting applied migrations when some exist."""
        await migration_manager.init()

        # Insert some test migrations
        async with aiosqlite.connect(migration_manager.db_path) as db:
            await db.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                ("0001_init", "2024-01-01 00:00:00"),
            )
            await db.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                ("0002_add_indexes", "2024-01-02 00:00:00"),
            )
            await db.commit()

        applied = await migration_manager.get_applied_migrations()
        assert applied == {"0001_init", "0002_add_indexes"}

    async def test_get_pending_migrations(
        self, migration_manager: MigrationManager
    ) -> None:
        """Test getting pending migrations."""
        # Create test migration files in the temporary migrations directory
        migrations_dir = migration_manager.migrations_dir

        # Create test migration files
        (migrations_dir / "0001_init.sql").write_text("CREATE TABLE test (id INTEGER);")
        (migrations_dir / "0002_add_indexes.sql").write_text(
            "CREATE INDEX idx_test_id ON test(id);"
        )
        (migrations_dir / "0003_add_fts.sql").write_text(
            "CREATE VIRTUAL TABLE test_fts USING fts5(content);"
        )

        await migration_manager.init()

        # Initially all migrations are pending
        pending = await migration_manager.get_pending_migrations()
        assert pending == ["0001_init", "0002_add_indexes", "0003_add_fts"]

        # Apply first migration
        await migration_manager.apply_migration("0001_init")

        # Check pending again
        pending = await migration_manager.get_pending_migrations()
        assert pending == ["0002_add_indexes", "0003_add_fts"]

    async def test_apply_migration_success(
        self, migration_manager: MigrationManager
    ) -> None:
        """Test successfully applying a migration."""
        # Create test migration file in the temporary migrations directory
        migrations_dir = migration_manager.migrations_dir

        migration_sql = """
        CREATE TABLE test_table (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_test_name ON test_table(name);
        """
        (migrations_dir / "0001_test.sql").write_text(migration_sql)

        await migration_manager.init()
        await migration_manager.apply_migration("0001_test")

        # Verify table was created
        async with aiosqlite.connect(migration_manager.db_path) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'"
            )
            result = await cursor.fetchone()
            assert result is not None

            # Verify index was created
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_test_name'"
            )
            result = await cursor.fetchone()
            assert result is not None

            # Verify migration was recorded
            cursor = await db.execute(
                "SELECT version FROM schema_migrations WHERE version = ?",
                ("0001_test",),
            )
            result = await cursor.fetchone()
            assert result is not None
            assert result[0] == "0001_test"

    async def test_apply_migration_failure(
        self, migration_manager: MigrationManager
    ) -> None:
        """Test applying a migration with invalid SQL."""
        # Create test migration file with invalid SQL in the temporary migrations directory
        migrations_dir = migration_manager.migrations_dir

        (migrations_dir / "0001_invalid.sql").write_text("INVALID SQL STATEMENT;")

        await migration_manager.init()

        with pytest.raises(
            MigrationError, match="Failed to apply migration 0001_invalid"
        ):
            await migration_manager.apply_migration("0001_invalid")

        # Verify migration was not recorded
        async with aiosqlite.connect(migration_manager.db_path) as db:
            cursor = await db.execute(
                "SELECT version FROM schema_migrations WHERE version = ?",
                ("0001_invalid",),
            )
            result = await cursor.fetchone()
            assert result is None

    async def test_apply_migration_idempotency(
        self, migration_manager: MigrationManager
    ) -> None:
        """Test that applying the same migration twice doesn't cause issues."""
        # Create test migration file in the temporary migrations directory
        migrations_dir = migration_manager.migrations_dir

        (migrations_dir / "0001_idempotent.sql").write_text(
            "CREATE TABLE idempotent_test (id INTEGER);"
        )

        await migration_manager.init()

        # Apply migration first time
        await migration_manager.apply_migration("0001_idempotent")

        # Apply migration second time - should not fail
        await migration_manager.apply_migration("0001_idempotent")

        # Verify table still exists and migration recorded only once
        async with aiosqlite.connect(migration_manager.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = ?",
                ("0001_idempotent",),
            )
            result = await cursor.fetchone()
            assert result[0] == 1

    async def test_migrate_all(self, migration_manager: MigrationManager) -> None:
        """Test migrating all pending migrations."""
        # Create test migration files in the temporary migrations directory
        migrations_dir = migration_manager.migrations_dir

        (migrations_dir / "0001_first.sql").write_text(
            "CREATE TABLE first (id INTEGER);"
        )
        (migrations_dir / "0002_second.sql").write_text(
            "CREATE TABLE second (id INTEGER);"
        )
        (migrations_dir / "0003_third.sql").write_text(
            "CREATE TABLE third (id INTEGER);"
        )

        await migration_manager.init()

        # Migrate all
        applied = await migration_manager.migrate_all()
        assert applied == ["0001_first", "0002_second", "0003_third"]

        # Verify all tables were created
        async with aiosqlite.connect(migration_manager.db_path) as db:
            for table in ["first", "second", "third"]:
                cursor = await db.execute(
                    f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'"
                )
                result = await cursor.fetchone()
                assert result is not None

            # Verify all migrations were recorded
            cursor = await db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
            results = await cursor.fetchall()
            assert [row[0] for row in results] == [
                "0001_first",
                "0002_second",
                "0003_third",
            ]

    async def test_migration_file_not_found(
        self, migration_manager: MigrationManager
    ) -> None:
        """Test error when migration file doesn't exist."""
        await migration_manager.init()

        with pytest.raises(
            MigrationError, match="Migration file not found: 0001_nonexistent"
        ):
            await migration_manager.apply_migration("0001_nonexistent")
