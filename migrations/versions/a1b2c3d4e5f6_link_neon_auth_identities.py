"""link neon auth identities and request windows"""

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "580852d9f992"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("neon_auth_id", sa.UUID(), nullable=True))
    op.add_column("users", sa.Column("email", sa.String(length=320), nullable=True))
    op.create_unique_constraint("uq_users_neon_auth_id", "users", ["neon_auth_id"])
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.create_table(
        "request_windows",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "window_start",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade():
    op.drop_table("request_windows")
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_constraint("uq_users_neon_auth_id", "users", type_="unique")
    op.drop_column("users", "email")
    op.drop_column("users", "neon_auth_id")
