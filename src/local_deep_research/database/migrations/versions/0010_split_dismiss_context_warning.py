"""Split shared dismiss_context_reduced into two per-warning keys.

Until now both context warnings (`context_below_history` and
`context_truncation_history`) shared a single dismiss key
(`app.warnings.dismiss_context_reduced`). Dismissing one dismissed both.

This migration splits the key in two so users can dismiss each warning
independently:

- `app.warnings.dismiss_context_below_history`
- `app.warnings.dismiss_context_truncation_history`

If a user already dismissed the old key, the dismissal is preserved on
both new keys (more permissive option — they previously chose to
silence both signals, so don't surprise them by un-silencing one).

Downgrade: best-effort. Re-creates the legacy single key from the
truncation-history value if available; otherwise from the below-history
value; otherwise no-op. The two new keys are deleted.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

OLD_KEY = "app.warnings.dismiss_context_reduced"
NEW_KEYS = [
    (
        "app.warnings.dismiss_context_below_history",
        'Dismiss "Context Below Historical Usage" Warning',
        (
            "Suppresses the front-page warning that fires when the configured "
            "context window is below the size that 99% of past researches ran with."
        ),
    ),
    (
        "app.warnings.dismiss_context_truncation_history",
        'Dismiss "Previous Truncation Detected" Warning',
        (
            "Suppresses the front-page warning that fires when previous "
            "researches were truncated at the same or higher context size."
        ),
    ),
]


def upgrade() -> None:
    """Split the shared dismiss key into two per-warning keys."""
    conn = op.get_bind()
    inspector = inspect(conn)
    if not inspector.has_table("settings"):
        return

    # Read existing dismissal value (default False if no row)
    old_row = conn.execute(
        sa.text(
            "SELECT value, type, category, ui_element, options, "
            "min_value, max_value, step, visible, editable, env_var "
            "FROM settings WHERE key = :key"
        ),
        {"key": OLD_KEY},
    ).fetchone()

    for new_key, new_name, new_description in NEW_KEYS:
        # Skip if the new key already exists (don't overwrite a fresh setting)
        already_exists = conn.execute(
            sa.text("SELECT COUNT(*) FROM settings WHERE key = :key"),
            {"key": new_key},
        ).scalar()
        if already_exists:
            continue

        if old_row is not None:
            # Carry forward the user's existing dismissal value + metadata
            conn.execute(
                sa.text(
                    "INSERT INTO settings "
                    "(key, value, type, name, description, category, "
                    "ui_element, options, min_value, max_value, step, "
                    "visible, editable, env_var) "
                    "VALUES (:key, :value, :type, :name, :description, "
                    ":category, :ui_element, :options, :min_value, "
                    ":max_value, :step, :visible, :editable, :env_var)"
                ),
                {
                    "key": new_key,
                    "value": old_row.value,
                    "type": old_row.type,
                    "name": new_name,
                    "description": new_description,
                    "category": old_row.category,
                    "ui_element": old_row.ui_element,
                    "options": old_row.options,
                    "min_value": old_row.min_value,
                    "max_value": old_row.max_value,
                    "step": old_row.step,
                    "visible": old_row.visible,
                    "editable": old_row.editable,
                    "env_var": old_row.env_var,
                },
            )

    # Drop the old key after both new keys exist (or if no migration was
    # needed because the key didn't exist in the first place).
    if old_row is not None:
        conn.execute(
            sa.text("DELETE FROM settings WHERE key = :key"),
            {"key": OLD_KEY},
        )


def downgrade() -> None:
    """Best-effort restore of the legacy single key.

    Picks the truncation-history value if present, else the below-history
    value, else no-op. Then drops both new keys. Imperfect since two
    independent dismissals collapse back to one — accepted trade-off
    for a downgrade path.
    """
    conn = op.get_bind()
    inspector = inspect(conn)
    if not inspector.has_table("settings"):
        return

    # Pick the better source row, preferring truncation_history.
    source_row = None
    for new_key, _, _ in reversed(NEW_KEYS):
        row = conn.execute(
            sa.text(
                "SELECT value, type, category, ui_element, options, "
                "min_value, max_value, step, visible, editable, env_var "
                "FROM settings WHERE key = :key"
            ),
            {"key": new_key},
        ).fetchone()
        if row is not None:
            source_row = row
            break

    if source_row is not None:
        # Recreate the legacy key only if it doesn't already exist.
        old_exists = conn.execute(
            sa.text("SELECT COUNT(*) FROM settings WHERE key = :key"),
            {"key": OLD_KEY},
        ).scalar()
        if not old_exists:
            conn.execute(
                sa.text(
                    "INSERT INTO settings "
                    "(key, value, type, name, description, category, "
                    "ui_element, options, min_value, max_value, step, "
                    "visible, editable, env_var) "
                    "VALUES (:key, :value, :type, :name, :description, "
                    ":category, :ui_element, :options, :min_value, "
                    ":max_value, :step, :visible, :editable, :env_var)"
                ),
                {
                    "key": OLD_KEY,
                    "value": source_row.value,
                    "type": source_row.type,
                    "name": "Dismiss Context Reduced Warning",
                    "description": "Legacy combined dismiss key.",
                    "category": source_row.category,
                    "ui_element": source_row.ui_element,
                    "options": source_row.options,
                    "min_value": source_row.min_value,
                    "max_value": source_row.max_value,
                    "step": source_row.step,
                    "visible": source_row.visible,
                    "editable": source_row.editable,
                    "env_var": source_row.env_var,
                },
            )

    for new_key, _, _ in NEW_KEYS:
        conn.execute(
            sa.text("DELETE FROM settings WHERE key = :key"),
            {"key": new_key},
        )
