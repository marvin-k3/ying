"""Database migration management for ying."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite


class MigrationError(Exception):
    """Raised when a migration operation fails."""

    pass


class MigrationManager:
    """Manages database schema migrations."""

    def __init__(self, db_path: Path) -> None:
        """Initialize the migration manager.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self.migrations_dir = Path(__file__).parent / "migrations"

    async def init(self) -> None:
        """Initialize the migration system by creating the schema_migrations table."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

    async def get_applied_migrations(self) -> set[str]:
        """Get the set of applied migration versions.

        Returns:
            Set of migration version strings.
        """
        await self.init()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT version FROM schema_migrations")
            rows = await cursor.fetchall()
            return {row[0] for row in rows}

    async def get_pending_migrations(self) -> list[str]:
        """Get the list of pending migration versions.

        Returns:
            List of migration version strings in order.
        """
        applied = await self.get_applied_migrations()

        # Get all migration files
        migration_files = []
        if self.migrations_dir.exists():
            for file_path in self.migrations_dir.glob("*.sql"):
                version = file_path.stem
                migration_files.append(version)

        # Sort by version (lexicographic order)
        migration_files.sort()

        # Return only pending migrations
        return [version for version in migration_files if version not in applied]

    async def apply_migration(self, version: str) -> None:
        """Apply a specific migration.

        Args:
            version: The migration version to apply.

        Raises:
            MigrationError: If the migration fails or file is not found.
        """
        migration_file = self.migrations_dir / f"{version}.sql"

        if not migration_file.exists():
            raise MigrationError(f"Migration file not found: {version}")

        # Check if already applied
        applied = await self.get_applied_migrations()
        if version in applied:
            return  # Already applied, skip

        # Read and execute migration SQL
        sql = migration_file.read_text()

        async with aiosqlite.connect(self.db_path) as db:
            try:
                # Execute the migration SQL
                await db.executescript(sql)

                # Record the migration
                await db.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, datetime.now(UTC).isoformat()),
                )

                await db.commit()

            except Exception as e:
                await db.rollback()
                raise MigrationError(f"Failed to apply migration {version}: {e}") from e

    async def migrate_all(self) -> list[str]:
        """Apply all pending migrations.

        Returns:
            List of applied migration versions.
        """
        pending = await self.get_pending_migrations()
        applied = []

        for version in pending:
            await self.apply_migration(version)
            applied.append(version)

        return applied


async def main() -> None:
    """Main entry point for running migrations."""
    import sys

    from app.config import Config

    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1])
    else:
        config = Config()
        db_path = Path(config.db_path)

    manager = MigrationManager(db_path)
    applied = await manager.migrate_all()

    if applied:
        print(f"Applied {len(applied)} migrations: {', '.join(applied)}")
    else:
        print("No pending migrations to apply.")


if __name__ == "__main__":
    asyncio.run(main())
