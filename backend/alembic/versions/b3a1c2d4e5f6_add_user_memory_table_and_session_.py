"""add user_memory table and session.summary_generated

Revision ID: b3a1c2d4e5f6
Revises: 0bab2fe13bc2
Create Date: 2026-04-30 17:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'b3a1c2d4e5f6'
down_revision: Union[str, None] = '0bab2fe13bc2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # session 表新增 summary_generated 字段
    op.add_column('session', sa.Column('summary_generated', sa.Boolean(), nullable=False, server_default=sa.text('0')))

    # 新建 user_memory 表
    op.create_table('user_memory',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('source_sessions', sa.JSON(), nullable=True),
        sa.Column('token_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('user_memory')
    op.drop_column('session', 'summary_generated')
