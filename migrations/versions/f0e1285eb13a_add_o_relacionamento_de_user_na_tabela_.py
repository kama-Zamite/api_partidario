"""add o relacionamento de user na tabela de SolicitacaoCartao

Revision ID: f0e1285eb13a
Revises: 8e680f4c9623
Create Date: 2026-09-03 07:28:41.233137

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0e1285eb13a'
down_revision: Union[str, Sequence[str], None] = '8e680f4c9623'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
