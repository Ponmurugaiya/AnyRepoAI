"""Data access layer: repository pattern implementations.

Each repository encapsulates all database queries for a single aggregate root.
Repositories accept a SQLAlchemy AsyncSession injected via FastAPI's DI system.
"""
