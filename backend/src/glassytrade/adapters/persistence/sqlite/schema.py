"""SQL for the versioned execution database."""

SCHEMA_MIGRATIONS = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""

EXECUTION_CORE = """
CREATE TABLE IF NOT EXISTS execution_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    aggregate_id TEXT NOT NULL,
    aggregate_sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    occurred_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    causation_id TEXT,
    payload_json TEXT NOT NULL,
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (aggregate_id, aggregate_sequence)
);
CREATE INDEX IF NOT EXISTS ix_execution_events_aggregate
    ON execution_events (aggregate_id, aggregate_sequence);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_sequence INTEGER NOT NULL UNIQUE REFERENCES execution_events(sequence),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0
);
"""

PROJECTIONS = """
CREATE TABLE IF NOT EXISTS order_intents (
    intent_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    contract_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    side TEXT NOT NULL,
    requested_quantity INTEGER NOT NULL,
    request_hash TEXT NOT NULL,
    reference_price TEXT,
    stop_price TEXT,
    target_price TEXT,
    status TEXT NOT NULL,
    created_sequence INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_attempts (
    attempt_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL,
    status TEXT NOT NULL,
    broker_order_id TEXT,
    correlation_id TEXT NOT NULL,
    requested_quantity INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (intent_id) REFERENCES order_intents(intent_id)
);
CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price TEXT NOT NULL,
    fees TEXT NOT NULL,
    filled_at TEXT NOT NULL,
    event_sequence INTEGER NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS positions (
    contract_id TEXT PRIMARY KEY,
    position_id TEXT NOT NULL,
    signed_quantity INTEGER NOT NULL,
    average_entry TEXT NOT NULL,
    current_stop TEXT,
    state TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS risk_reservations (
    reservation_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    amount TEXT NOT NULL,
    released_amount TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS protection_orders (
    receipt_id TEXT PRIMARY KEY,
    position_id TEXT NOT NULL,
    status TEXT NOT NULL,
    desired_stop TEXT NOT NULL,
    effective_stop TEXT,
    broker_order_id TEXT,
    protection_quantity INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""

RECONCILIATION = """
CREATE TABLE IF NOT EXISTS reconciliation_cases (
    case_id TEXT PRIMARY KEY,
    contract_id TEXT,
    discrepancy TEXT NOT NULL,
    expected_state TEXT NOT NULL,
    observed_state TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS broker_receipts (
    receipt_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL
);
"""
