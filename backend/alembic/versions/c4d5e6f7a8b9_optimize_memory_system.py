"""optimize memory system: UserMemory.add session_id, Session.replace summary_generated with last_summarized_message_id

Revision ID: c4d5e6f7a8b9
Revises: b3a1c2d4e5f6
Create Date: 2026-05-04 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3a1c2d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # user_memory 表新增 session_id 字段（L2 关联会话）
    op.add_column('user_memory', sa.Column('session_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_user_memory_session', 'user_memory', 'session', ['session_id'], ['id'])

    # session 表：删除 summary_generated，新增 last_summarized_message_id
    op.add_column('session', sa.Column('last_summarized_message_id', sa.Integer(), nullable=True))
    op.drop_column('session', 'summary_generated')


def downgrade() -> None:
    # 恢复 session 表
    op.add_column('session', sa.Column('summary_generated', sa.Boolean(), nullable=False, server_default=sa.text('0')))
    op.drop_column('session', 'last_summarized_message_id')

    # 删除 user_memory.session_id
    op.drop_constraint('fk_user_memory_session', 'user_memory', type_='foreignkey')
    op.drop_column('user_memory', 'session_id')
