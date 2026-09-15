import sqlalchemy as sa

metadata = sa.MetaData()

events_table = sa.Table(
    "events",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("installation_id", sa.Integer, nullable=False),
    sa.Column("repo", sa.String, nullable=False),
    sa.Column("sha", sa.String, nullable=False),
    sa.Column("event_type", sa.String, nullable=False),
    sa.Column("owner", sa.String, nullable=False),
    sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint(
        "installation_id", "repo", "sha", "event_type", "owner", name="ux_events_dedupe_key"
    ),
    sa.Index("ix_events_budget_query", "installation_id", "owner", "ts"),
)

tenant_config_table = sa.Table(
    "tenant_config",
    metadata,
    sa.Column("installation_id", sa.Integer, primary_key=True),
    sa.Column("rolling_window_days", sa.Integer, nullable=False),
    sa.Column("default_team", sa.String, nullable=False),
    sa.Column("max_events_per_window", sa.Integer, nullable=False),
    sa.Column("warn_threshold_pct", sa.Integer, nullable=False),
)
