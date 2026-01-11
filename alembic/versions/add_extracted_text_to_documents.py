"""Add extracted_text column to documents table

Revision ID: add_extracted_text_to_documents
Revises: 
Create Date: 2026-01-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_extracted_text_to_documents'
down_revision = None  # Mettez l'ID de la dernière migration ici si vous en avez une
branch_labels = None
depends_on = None


def upgrade():
    # Ajouter la colonne extracted_text à la table documents
    op.add_column('documents', sa.Column('extracted_text', sa.Text(), nullable=True))


def downgrade():
    # Supprimer la colonne extracted_text
    op.drop_column('documents', 'extracted_text')
