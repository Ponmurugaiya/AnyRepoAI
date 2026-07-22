-- PostgreSQL initialization script
-- Runs once when the container is first created.

-- Enable useful extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- UUID generation
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- Trigram similarity for text search
CREATE EXTENSION IF NOT EXISTS "btree_gin";   -- GIN indexing for composite queries

-- Confirm setup
DO $$
BEGIN
    RAISE NOTICE 'PostgreSQL initialized successfully for Codebase Intelligence Platform';
END $$;
