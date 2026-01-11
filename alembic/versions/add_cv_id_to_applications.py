"""Add cv_id to applications table

Revision ID: add_cv_id_to_applications
Revises: add_extracted_text_to_documents
Create Date: 2026-01-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_cv_id_to_applications'
down_revision = 'add_extracted_text_to_documents'
branch_labels = None
depends_on = None


def upgrade():
    # Ajouter la colonne cv_id à la table applications
    op.add_column('applications', sa.Column('cv_id', sa.UUID(), nullable=True))
    
    # Créer la contrainte de clé étrangère
    op.create_foreign_key(
        'fk_applications_cv_id_documents',
        'applications', 'documents',
        ['cv_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade():
    # Supprimer la contrainte et la colonne
    op.drop_constraint('fk_applications_cv_id_documents', 'applications', type_='foreignkey')
    op.drop_column('applications', 'cv_id')
