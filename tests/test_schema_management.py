from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect

from app.schema_management import migrate_registered_schema


def test_non_owner_does_not_create_tables(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    Table("proof", metadata, Column("id", Integer, primary_key=True))
    monkeypatch.setenv("SCHEMA_MANAGEMENT_MODE", "migrate_once")
    monkeypatch.setenv("SCHEMA_MIGRATION_OWNER", "0")
    result = migrate_registered_schema(engine, metadata)
    assert result["executed"] is False
    assert inspect(engine).has_table("proof") is False


def test_owner_creates_registered_schema_once(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    Table("proof", metadata, Column("id", Integer, primary_key=True))
    monkeypatch.setenv("SCHEMA_MANAGEMENT_MODE", "migrate_once")
    monkeypatch.setenv("SCHEMA_MIGRATION_OWNER", "1")
    assert migrate_registered_schema(engine, metadata)["executed"] is True
    assert inspect(engine).has_table("proof") is True
    assert migrate_registered_schema(engine, metadata)["executed"] is True
