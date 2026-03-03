"""
API router configuration.

This module configures the API router by including all endpoint modules
and applying appropriate prefixes and tags.
"""

from fastapi import APIRouter

from backend.app.api.v1.endpoints import (
    auth,
    users,
    experiments,
    tracking,
    feature_flags,
    admin,
    assignments,
    events,
    results,
    rollout_schedules,
    metrics,
    safety,
    audit_logs,
    export,
    bulk_toggle,
    rbac,
    realtime_counters,
    etl,
    scheduler_health,
    segments,
    mutual_exclusion_groups,
    global_holdout,
    bandit,
    interactions,
    ai_design,
    mcp,
    experiment_wizard,
    warehouse,
    notifications,
    compliance,
    integrations,
)

# Import the sample size calculator router
from backend.app.api.v1.sample_size_calculator import router as sample_size_router
# from backend.app.routers import feature_flag_routes

# Create API router for v1
api_router_v1 = APIRouter()

# Include endpoint routers with appropriate prefixes and tags
api_router_v1.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router_v1.include_router(users.router, prefix="/users", tags=["Users"])
api_router_v1.include_router(
    experiments.router, prefix="/experiments", tags=["Experiments"]
)
api_router_v1.include_router(tracking.router, prefix="/tracking", tags=["Tracking"])
api_router_v1.include_router(
    feature_flags.router, prefix="/feature-flags", tags=["Feature Flags"]
)
api_router_v1.include_router(admin.router, prefix="/admin", tags=["Administration"])
api_router_v1.include_router(
    assignments.router, prefix="/assignments", tags=["Assignments"]
)
api_router_v1.include_router(events.router, prefix="/events", tags=["Events"])
api_router_v1.include_router(results.router, prefix="/results", tags=["Results"])
api_router_v1.include_router(
    rollout_schedules.router, prefix="/rollout-schedules", tags=["Rollout Schedules"]
)
api_router_v1.include_router(
    metrics.router, prefix="/metrics", tags=["Metrics"]
)
api_router_v1.include_router(
    safety.router, prefix="/safety", tags=["Safety"]
)
api_router_v1.include_router(
    audit_logs.router, prefix="/audit-logs", tags=["Audit Logs"]
)

# Add new utility endpoints
api_router_v1.include_router(sample_size_router, prefix="/utils", tags=["Utilities"])

# EP-020: Data Export & Reporting
api_router_v1.include_router(export.router, prefix="/export", tags=["Export"])

# P1-B: Advanced Toggle Features & Audit Logging
api_router_v1.include_router(bulk_toggle.router, prefix="", tags=["Advanced Toggle"])

# P2-A: RBAC Post-MVP Enhancements
api_router_v1.include_router(rbac.router, prefix="/rbac", tags=["RBAC"])

# P2-B: Real-time Counters in DynamoDB
api_router_v1.include_router(
    realtime_counters.router, prefix="/counters", tags=["Real-time Counters"]
)

# P3-A: ETL & Glue Jobs for S3 Data Lake
api_router_v1.include_router(etl.router, prefix="/etl", tags=["ETL"])

# P3-B: Scheduler Enhancements — health, history, and notifications
api_router_v1.include_router(
    scheduler_health.router, prefix="/scheduler", tags=["Scheduler Health"]
)

# P3-C: Audience Segmentation API
api_router_v1.include_router(
    segments.router, prefix="/segments", tags=["Segments"]
)

# EP-022: Mutual Exclusion Groups & Global Holdout
api_router_v1.include_router(
    mutual_exclusion_groups.router, prefix="/mutual-exclusion-groups",
    tags=["Mutual Exclusion Groups"]
)
api_router_v1.include_router(
    global_holdout.router, prefix="/holdout", tags=["Global Holdout"]
)

# Issue #22: Multi-Armed Bandit (MAB) endpoints
api_router_v1.include_router(
    bandit.router, prefix="/bandit", tags=["Bandit"]
)

# Issue #25: Cross-Experiment Interaction Detection & Analysis
api_router_v1.include_router(
    interactions.router, prefix="/interactions", tags=["Interactions"]
)

# Issue #23: AI-Powered Experiment Design & Recommendations
api_router_v1.include_router(
    ai_design.router, prefix="/ai", tags=["AI Design"]
)

# Issue #23: MCP (Model Context Protocol) server for AI agent access
api_router_v1.include_router(
    mcp.router, prefix="/mcp", tags=["MCP"]
)

# Issue #27: No-Code Visual Experiment Wizard (EP-003 Extension)
api_router_v1.include_router(
    experiment_wizard.router, prefix="/wizard", tags=["Experiment Wizard"]
)

# Issue #26: POST-MVP Warehouse-Native Analytics (Snowflake / BigQuery / Redshift)
api_router_v1.include_router(
    warehouse.router, prefix="/warehouse", tags=["Warehouse"]
)

# EP-030: Notification preferences and delivery log
api_router_v1.include_router(
    notifications.router, prefix="/notifications", tags=["Notifications"]
)

# EP-033: Compliance Audit Logging
api_router_v1.include_router(
    compliance.router, prefix="/compliance", tags=["Compliance"]
)

# EP-034: Integration Config Management (Salesforce / Jira / GitHub)
api_router_v1.include_router(
    integrations.router, prefix="/integrations", tags=["Integrations"]
)

# Main API router that includes versioned routers
api_router = APIRouter()
api_router.include_router(api_router_v1)

# Documentation configuration
tags_metadata = [
    {
        "name": "Authentication",
        "description": "Operations for user authentication, registration and token management",
    },
    {
        "name": "Users",
        "description": "Operations for managing user accounts and profiles",
    },
    {
        "name": "Experiments",
        "description": "Operations for creating, managing and analyzing A/B tests and experiments",
    },
    {
        "name": "Tracking",
        "description": "Operations for tracking user interactions and experiment events",
    },
    {
        "name": "Feature Flags",
        "description": "Operations for managing feature flags and gradual rollouts",
    },
    {
        "name": "Assignments",
        "description": "Operations for managing user assignments to experiment variants",
    },
    {
        "name": "Events",
        "description": "Operations for querying and managing tracking events",
    },
    {
        "name": "Results",
        "description": "Operations for viewing results and analysis of experiments",
    },
    {
        "name": "Administration",
        "description": "Operations for system administration and management",
    },
    {
        "name": "Utilities",
        "description": "Utility operations for experiment design and planning",
    },
    {
        "name": "Rollout Schedules",
        "description": "Operations for managing gradual feature flag rollout schedules",
    },
    {
        "name": "Metrics",
        "description": "Operations for retrieving and analyzing feature flag metrics and performance data",
    },
    {
        "name": "Safety",
        "description": "Operations for monitoring feature flag safety and managing rollbacks",
    },
    {
        "name": "Audit Logs",
        "description": "Operations for querying audit logs and tracking system activity",
    },
    {
        "name": "Export",
        "description": "Operations for exporting experiment and feature flag data as CSV or JSON",
    },
    {
        "name": "Reports",
        "description": "Operations for generating platform and experiment summary reports",
    },
    {
        "name": "RBAC",
        "description": "Operations for managing custom roles, permission delegation, and effective permission resolution",
    },
    {
        "name": "Real-time Counters",
        "description": "Real-time DynamoDB atomic counters for experiment assignments, events, and conversions",
    },
    {
        "name": "ETL",
        "description": "Operations for managing AWS Glue ETL jobs, Athena queries, S3 partitions, and Glue crawlers",
    },
    {
        "name": "Scheduler Health",
        "description": "Operations for monitoring background scheduler health, run history, and webhook notifications",
    },
    {
        "name": "Segments",
        "description": "Operations for creating and managing audience segments and evaluating user membership",
    },
    {
        "name": "Mutual Exclusion Groups",
        "description": "Operations for managing mutual exclusion groups that prevent users from being in conflicting experiments",
    },
    {
        "name": "Global Holdout",
        "description": "Operations for managing global holdout configurations that reserve a percentage of users from all experiments",
    },
    {
        "name": "Interactions",
        "description": "Cross-experiment interaction detection: overlap analysis, statistical interaction tests, novelty effect detection, and SUTVA violation checks",
    },
    {
        "name": "AI Design",
        "description": "AI-powered experiment design assistant, results interpretation, sample size calculator, and experiment template library",
    },
    {
        "name": "MCP",
        "description": "Model Context Protocol server — exposes platform APIs to AI coding assistants and agents",
    },
    {
        "name": "Experiment Wizard",
        "description": "No-code step-by-step wizard for non-technical users to design and launch experiments",
    },
    {
        "name": "Warehouse",
        "description": (
            "Warehouse-Native Analytics: manage Snowflake, BigQuery, and Redshift "
            "connections, generate experiment analysis SQL, and sync results directly "
            "from customer data warehouses. Credentials stored encrypted."
        ),
    },
    {
        "name": "Compliance",
        "description": (
            "SOC 2 Type 2 / ISO 27001 compliance audit trail. "
            "HMAC-signed, append-only events with configurable retention. "
            "Accessible to ADMIN and ANALYST roles only."
        ),
    },
]
