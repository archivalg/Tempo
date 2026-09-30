#!/bin/sh
# Creates Tempo's separate migration/owner and runtime roles and the dev/test databases.
# Runs once, on first init of the data volume. tempo_owner owns schema objects and runs
# migrations; tempo_app is the API/worker runtime role: no ownership, no BYPASSRLS.
set -eu
psql -v ON_ERROR_STOP=1 -U postgres <<SQL
CREATE ROLE tempo_owner LOGIN PASSWORD '${TEMPO_DB_OWNER_PASSWORD}' NOSUPERUSER NOBYPASSRLS NOCREATEROLE;
CREATE ROLE tempo_app   LOGIN PASSWORD '${TEMPO_DB_APP_PASSWORD}'   NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
CREATE DATABASE tempo      OWNER tempo_owner;
CREATE DATABASE tempo_test OWNER tempo_owner;
SQL
for db in tempo tempo_test; do
psql -v ON_ERROR_STOP=1 -U postgres -d "$db" <<SQL
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO tempo_owner;
GRANT USAGE ON SCHEMA public TO tempo_app;
ALTER DEFAULT PRIVILEGES FOR ROLE tempo_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tempo_app;
ALTER DEFAULT PRIVILEGES FOR ROLE tempo_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO tempo_app;
SQL
done
