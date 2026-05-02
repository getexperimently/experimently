#!/usr/bin/env python3
"""
Check the database against migration files and apply any missing DDL.
"""
import psycopg2

CONN_STR = "postgresql://postgres:postgres@localhost:5432/experimentation"
SCHEMA = "experimentation"


def main():
    conn = psycopg2.connect(CONN_STR)
    conn.autocommit = False
    cur = conn.cursor()

    # ------------------------------------------------------------------
    # Introspect existing state
    # ------------------------------------------------------------------
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = %s AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """, (SCHEMA,))
    existing_tables = {row[0] for row in cur.fetchall()}

    cur.execute("""
        SELECT t.typname FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE t.typtype = 'e'
    """)
    all_enums = {row[0] for row in cur.fetchall()}

    def cols(table):
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
        """, (SCHEMA, table))
        return {row[0] for row in cur.fetchall()}

    print("=" * 70)
    print("EXISTING TABLES:", sorted(existing_tables))
    print("ALL ENUMS:", sorted(all_enums))
    print("=" * 70)

    # Accumulate SQL to run
    todo = []  # list of (description, sql)

    def need_enum(name, definition):
        if name not in all_enums:
            todo.append((f"CREATE ENUM {name}", definition))

    def need_table(name, definition):
        if name not in existing_tables:
            todo.append((f"CREATE TABLE {name}", definition))

    def need_col(table, col, definition):
        if table in existing_tables and col not in cols(table):
            todo.append((f"ADD COLUMN {table}.{col}", definition))

    # ------------------------------------------------------------------
    # EP-030: notification_delivery_log, notification_preferences
    # (plus many core tables already expected to exist)
    # ------------------------------------------------------------------
    need_enum('notification_channel',
        f"CREATE TYPE {SCHEMA}.notification_channel AS ENUM ('SLACK','EMAIL','WEBHOOK');")
    need_enum('notification_status',
        f"CREATE TYPE {SCHEMA}.notification_status AS ENUM ('SENT','FAILED','SKIPPED');")

    need_table('notification_delivery_log', f"""
CREATE TABLE {SCHEMA}.notification_delivery_log (
    id UUID NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    channel {SCHEMA}.notification_channel NOT NULL,
    recipient VARCHAR(512) NOT NULL,
    subject VARCHAR(512),
    status {SCHEMA}.notification_status NOT NULL,
    error_message TEXT,
    payload JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);""")

    need_table('notification_preferences', f"""
CREATE TABLE {SCHEMA}.notification_preferences (
    id UUID NOT NULL,
    user_id UUID NOT NULL,
    notify_experiment_started BOOLEAN NOT NULL DEFAULT false,
    notify_experiment_completed BOOLEAN NOT NULL DEFAULT false,
    notify_safety_rollback BOOLEAN NOT NULL DEFAULT false,
    notify_rollout_advanced BOOLEAN NOT NULL DEFAULT false,
    slack_channel VARCHAR(255),
    email_override VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    FOREIGN KEY (user_id) REFERENCES {SCHEMA}.users(id) ON DELETE CASCADE,
    PRIMARY KEY (id),
    UNIQUE (user_id)
);""")

    # ------------------------------------------------------------------
    # EP-033: audit_events_v2
    # ------------------------------------------------------------------
    need_enum('audit_action_type', f"""
CREATE TYPE {SCHEMA}.audit_action_type AS ENUM (
    'CREATE','READ','UPDATE','DELETE',
    'LOGIN','LOGOUT','LOGIN_FAILED',
    'ROLE_GRANT','ROLE_REVOKE',
    'KEY_CREATE','KEY_REVOKE',
    'EXPORT','REPORT_GENERATED'
);""")
    need_enum('audit_outcome_type',
        f"CREATE TYPE {SCHEMA}.audit_outcome_type AS ENUM ('SUCCESS','FAILURE','DENIED');")

    need_table('audit_events_v2', f"""
CREATE TABLE {SCHEMA}.audit_events_v2 (
    id UUID NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id UUID,
    actor_ip VARCHAR(45),
    actor_user_agent VARCHAR(512),
    session_id VARCHAR(128),
    request_id VARCHAR(128),
    action {SCHEMA}.audit_action_type NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource_id VARCHAR(128),
    old_value JSONB,
    new_value JSONB,
    outcome {SCHEMA}.audit_outcome_type NOT NULL,
    hmac_signature VARCHAR(64),
    archived_at TIMESTAMPTZ,
    retention_expires_at TIMESTAMPTZ,
    PRIMARY KEY (id)
);""")

    # ------------------------------------------------------------------
    # EP-034: integration_configs
    # ------------------------------------------------------------------
    # The migration creates this without a schema qualifier on the enum
    cur.execute("""
        SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
        WHERE t.typname='integration_type_enum'
    """)
    if not cur.fetchone():
        todo.append(("CREATE ENUM integration_type_enum",
            "CREATE TYPE integration_type_enum AS ENUM ('salesforce','jira','github');"))

    need_table('integration_configs', f"""
CREATE TABLE {SCHEMA}.integration_configs (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    integration_type integration_type_enum NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT false,
    encrypted_config JSONB,
    last_sync_at TIMESTAMPTZ,
    last_error VARCHAR(1024),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (integration_type)
);""")

    # ------------------------------------------------------------------
    # EP-035: bayesian columns on experiments
    # ------------------------------------------------------------------
    need_col('experiments', 'bayesian_enabled',
        f"ALTER TABLE {SCHEMA}.experiments ADD COLUMN IF NOT EXISTS bayesian_enabled BOOLEAN NOT NULL DEFAULT false;")
    need_col('experiments', 'bayesian_config',
        f"ALTER TABLE {SCHEMA}.experiments ADD COLUMN IF NOT EXISTS bayesian_config JSONB;")
    need_col('experiments', 'bayesian_decision',
        f"ALTER TABLE {SCHEMA}.experiments ADD COLUMN IF NOT EXISTS bayesian_decision VARCHAR(32);")

    # ------------------------------------------------------------------
    # EP-036: split_url_config on experiments
    # ------------------------------------------------------------------
    need_col('experiments', 'split_url_config',
        f"ALTER TABLE {SCHEMA}.experiments ADD COLUMN IF NOT EXISTS split_url_config JSONB;")

    # ------------------------------------------------------------------
    # EP-037: sso_configs + users.sso_provider
    # ------------------------------------------------------------------
    need_enum('ssoprovidertype', f"""
CREATE TYPE {SCHEMA}.ssoprovidertype AS ENUM (
    'saml','google','github','microsoft','okta','azure_ad','onelogin'
);""")

    need_table('sso_configs', f"""
CREATE TABLE {SCHEMA}.sso_configs (
    id UUID NOT NULL,
    org_name VARCHAR(255) NOT NULL,
    org_domain VARCHAR(255) NOT NULL,
    provider_type {SCHEMA}.ssoprovidertype NOT NULL,
    entity_id VARCHAR(1024),
    sso_url VARCHAR(2048),
    x509_certificate TEXT,
    client_secret VARCHAR(1024),
    role_mapping JSONB,
    is_enforced BOOLEAN NOT NULL DEFAULT false,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (org_domain)
);""")

    need_col('users', 'sso_provider',
        f"ALTER TABLE {SCHEMA}.users ADD COLUMN IF NOT EXISTS sso_provider VARCHAR(50);")

    # ------------------------------------------------------------------
    # EP-046: llm_experiments, llm_variants, llm_evaluations
    # ------------------------------------------------------------------
    need_enum('llmexperimentstatus',
        f"CREATE TYPE {SCHEMA}.llmexperimentstatus AS ENUM ('DRAFT','ACTIVE','PAUSED','COMPLETED');")
    need_enum('llmtasktype',
        f"CREATE TYPE {SCHEMA}.llmtasktype AS ENUM ('chat_completion','text_generation','classification','summarization','code_generation','embedding');")
    need_enum('llmevaluationmetric',
        f"CREATE TYPE {SCHEMA}.llmevaluationmetric AS ENUM ('human_rating','latency','cost','accuracy','relevance','fluency','business_metric');")
    need_enum('llmprovider',
        f"CREATE TYPE {SCHEMA}.llmprovider AS ENUM ('openai','anthropic','google','cohere','mistral','local');")

    need_table('llm_experiments', f"""
CREATE TABLE {SCHEMA}.llm_experiments (
    id UUID NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    status {SCHEMA}.llmexperimentstatus NOT NULL DEFAULT 'DRAFT',
    task_type {SCHEMA}.llmtasktype NOT NULL,
    evaluation_metric {SCHEMA}.llmevaluationmetric NOT NULL,
    experiment_id UUID REFERENCES {SCHEMA}.experiments(id) ON DELETE SET NULL,
    created_by UUID REFERENCES {SCHEMA}.users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);""")

    need_table('llm_variants', f"""
CREATE TABLE {SCHEMA}.llm_variants (
    id UUID NOT NULL,
    llm_experiment_id UUID NOT NULL REFERENCES {SCHEMA}.llm_experiments(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    is_control BOOLEAN NOT NULL DEFAULT false,
    traffic_split FLOAT NOT NULL DEFAULT 0.5,
    provider {SCHEMA}.llmprovider NOT NULL,
    model_name VARCHAR(200) NOT NULL,
    system_prompt TEXT,
    prompt_template TEXT NOT NULL,
    temperature FLOAT NOT NULL DEFAULT 0.7,
    max_tokens INTEGER NOT NULL DEFAULT 1000,
    additional_params JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT check_llm_traffic_split CHECK (traffic_split >= 0.0 AND traffic_split <= 1.0),
    PRIMARY KEY (id)
);""")

    need_table('llm_evaluations', f"""
CREATE TABLE {SCHEMA}.llm_evaluations (
    id UUID NOT NULL,
    llm_experiment_id UUID NOT NULL REFERENCES {SCHEMA}.llm_experiments(id) ON DELETE CASCADE,
    variant_id UUID NOT NULL REFERENCES {SCHEMA}.llm_variants(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    input_variables JSONB,
    rendered_prompt TEXT,
    model_response TEXT,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd FLOAT NOT NULL DEFAULT 0.0,
    human_rating FLOAT,
    auto_eval_score FLOAT,
    business_metric_value FLOAT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);""")

    # ------------------------------------------------------------------
    # Safety tables
    # ------------------------------------------------------------------
    need_table('safety_settings', f"""
CREATE TABLE {SCHEMA}.safety_settings (
    id UUID NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    enable_automatic_rollbacks BOOLEAN NOT NULL DEFAULT false,
    default_metrics JSONB,
    PRIMARY KEY (id)
);""")

    need_table('feature_flag_safety_configs', f"""
CREATE TABLE {SCHEMA}.feature_flag_safety_configs (
    id UUID NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    feature_flag_id UUID NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    metrics JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    rollback_percentage INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (feature_flag_id) REFERENCES {SCHEMA}.feature_flags(id) ON DELETE CASCADE,
    PRIMARY KEY (id)
);""")

    need_table('safety_rollback_records', f"""
CREATE TABLE {SCHEMA}.safety_rollback_records (
    id UUID NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    feature_flag_id UUID NOT NULL,
    safety_config_id UUID NOT NULL,
    trigger_type VARCHAR NOT NULL,
    trigger_reason TEXT NOT NULL,
    previous_percentage INTEGER NOT NULL,
    target_percentage INTEGER NOT NULL,
    success BOOLEAN NOT NULL DEFAULT false,
    executed_by_user_id UUID,
    FOREIGN KEY (feature_flag_id) REFERENCES {SCHEMA}.feature_flags(id) ON DELETE CASCADE,
    FOREIGN KEY (safety_config_id) REFERENCES {SCHEMA}.feature_flag_safety_configs(id) ON DELETE CASCADE,
    FOREIGN KEY (executed_by_user_id) REFERENCES {SCHEMA}.users(id) ON DELETE SET NULL,
    PRIMARY KEY (id)
);""")

    # ------------------------------------------------------------------
    # Summary and execution
    # ------------------------------------------------------------------
    if not todo:
        print("\nNothing to do — database schema is already up to date.")
    else:
        print(f"\n{len(todo)} statement(s) to execute:\n")
        for i, (desc, sql) in enumerate(todo, 1):
            print(f"  [{i}] {desc}")

        print("\nExecuting...\n")
        success_count = 0
        error_count = 0
        for desc, sql in todo:
            try:
                cur.execute(sql)
                conn.commit()
                print(f"  OK: {desc}")
                success_count += 1
            except Exception as e:
                conn.rollback()
                print(f"  ERROR: {desc}\n       {e}")
                error_count += 1

        print(f"\nDone: {success_count} succeeded, {error_count} failed.")

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
