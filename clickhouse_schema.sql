-- =============================================================================
-- TFT Analytics — ClickHouse Schema
-- =============================================================================
-- Run this script once to set up the ClickHouse database and tables.
-- Unlike PostgreSQL/Alembic, ClickHouse schema is managed via this SQL script.
--
-- To apply:
--   docker-compose exec clickhouse clickhouse-client --multiquery < clickhouse_schema.sql
-- =============================================================================

CREATE DATABASE IF NOT EXISTS tft;

USE tft;

-- =============================================================================
-- MAIN ANALYTICAL TABLE
-- One row per unit per participant per game.
-- A single 8-player game produces approximately 72 rows.
--
-- Partitioned by game_version (patch) — old partitions are dropped entirely
-- when a new patch is detected, no row-level deletes needed.
--
-- Sort key: (character_id, lp) — optimised for the most common query pattern
-- of filtering by champion then by player strength.
-- =============================================================================

CREATE TABLE IF NOT EXISTS tft.unit_stats
(
    -- -------------------------------------------------------------------------
    -- Match level
    -- -------------------------------------------------------------------------
    match_id        String,
    game_datetime   DateTime,
    game_version    String,       -- used for partitioning, e.g. "16.3"
    tft_set_number  UInt8,
    queue_id        UInt16,

    -- -------------------------------------------------------------------------
    -- Participant level
    -- -------------------------------------------------------------------------
    puuid                   String,
    placement               UInt8,    -- 1-8
    level                   UInt8,    -- player board level
    last_round              UInt8,
    gold_left               UInt8,
    players_eliminated      UInt8,
    total_damage_to_players UInt16,

    -- Player rank data — denormalized from league_entries at save time
    tier                    LowCardinality(String),   -- CHALLENGER, GRANDMASTER, MASTER, DIAMOND etc.
    rank                    LowCardinality(String),   -- I, II, III, IV (empty for Challenger/GM)
    lp                      UInt16,

    -- -------------------------------------------------------------------------
    -- Unit level
    -- -------------------------------------------------------------------------
    character_id    LowCardinality(String),   -- e.g. TFT16_Jinx
    unit_name       LowCardinality(String),   -- may be empty, kept for future use
    unit_tier       UInt8,                    -- star level (1, 2, 3)
    unit_rarity     UInt8,                    -- 0=1cost, 1=2cost, 2=3cost, 4=4cost, 6=5cost

    -- Items — nullable since units can have 0, 1, 2 or 3 items
    item_1          LowCardinality(String),   -- empty string if no item
    item_2          LowCardinality(String),
    item_3          LowCardinality(String)
)
ENGINE = MergeTree()
PARTITION BY game_version
ORDER BY (character_id, lp)
SETTINGS index_granularity = 8192;


-- =============================================================================
-- PROJECTION — item-first queries
-- Optimised for questions like "best champions for item X"
-- where base sort key (character_id, lp) is not helpful
-- =============================================================================

ALTER TABLE tft.unit_stats
    ADD PROJECTION IF NOT EXISTS proj_item_first
    (
        SELECT *
        ORDER BY (item_1, character_id, lp)
    );


-- =============================================================================
-- SKIPPING INDEXES
-- Secondary indexes for columns not in the sort key but commonly filtered
-- =============================================================================

-- Filter by tier (CHALLENGER, GRANDMASTER etc.)
ALTER TABLE tft.unit_stats
    ADD INDEX IF NOT EXISTS idx_tier tier TYPE set(10) GRANULARITY 1;

-- Filter by placement (e.g. top 4 finishes only)
ALTER TABLE tft.unit_stats
    ADD INDEX IF NOT EXISTS idx_placement placement TYPE set(8) GRANULARITY 1;
