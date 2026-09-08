-- Run as the schema owner AFTER migrations.
-- First create support_runtime as a login with a unique password using your secret manager.
-- Runtime must not own the database/schema, be superuser, or inherit owner privileges.
GRANT USAGE ON SCHEMA public TO support_runtime;
GRANT SELECT ON users TO support_runtime;
GRANT SELECT, UPDATE (window_start, requests) ON access_tokens TO support_runtime;
GRANT SELECT, INSERT, UPDATE (status, assignee_id, version) ON tickets TO support_runtime;
GRANT SELECT, INSERT ON comments, events TO support_runtime;
-- Administrative CLI and migrations use a separate owner credential, never the web process.
