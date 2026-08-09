"""recordasset with asset type geom data and nullable relative path

Revision ID: 421a23b83456
Revises: 51539465154f
Create Date: 2026-08-08 11:22:11.489801

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "421a23b83456"
down_revision: Union[str, Sequence[str], None] = "51539465154f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    sa.Enum("DATA", "THUMBNAIL", "PREVIEW", name="assettype").create(op.get_bind())
    op.add_column(
        "recordasset",
        sa.Column(
            "asset_type",
            postgresql.ARRAY(
                postgresql.ENUM(
                    "DATA", "THUMBNAIL", "PREVIEW", name="assettype", create_type=False
                )
            ),
            nullable=True,
        ),
    )
    op.add_geospatial_column(
        "recordasset",
        sa.Column(
            "geog",
            Geography(
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeogFromText",
                name="geography",
            ),
            nullable=True,
        ),
    )
    op.add_column("recordasset", sa.Column("data", sa.LargeBinary(), nullable=True))
    op.alter_column(
        "recordasset", "relative_path", existing_type=sa.VARCHAR(), nullable=True
    )
    op.execute("UPDATE recordasset SET relative_path = NULL WHERE relative_path = ''")
    op.execute("UPDATE recordasset SET asset_type = '{DATA}'::assettype[]")
    # missing media types follow the application/prs.ipma.<ext> convention of
    # the seeded asset discovery configurations
    op.execute(
        """
        UPDATE recordasset SET media_type =
          CASE WHEN relative_path ~ '\\.[A-Za-z0-9]+$'
               THEN 'application/prs.ipma.' || lower(substring(relative_path from '\\.([A-Za-z0-9]+)$'))
               ELSE 'application/octet-stream'
          END
        WHERE media_type IS NULL OR media_type = ''
        """
    )
    op.alter_column(
        "recordasset",
        "asset_type",
        existing_type=postgresql.ARRAY(
            postgresql.ENUM(
                "DATA", "THUMBNAIL", "PREVIEW", name="assettype", create_type=False
            )
        ),
        nullable=False,
    )
    op.alter_column(
        "recordasset", "media_type", existing_type=sa.VARCHAR(), nullable=False
    )
    op.create_geospatial_index(
        "idx_recordasset_geog",
        "recordasset",
        ["geog"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={},
    )
    # martin table sources query via a geometry cast, which the geography GiST
    # index cannot serve
    op.execute(
        "CREATE INDEX idx_recordasset_geog_geometry ON recordasset USING gist ((geog::geometry))"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX idx_recordasset_geog_geometry")
    op.drop_geospatial_index(
        "idx_recordasset_geog",
        table_name="recordasset",
        postgresql_using="gist",
        column_name="geog",
    )
    op.alter_column(
        "recordasset", "media_type", existing_type=sa.VARCHAR(), nullable=True
    )
    op.execute("UPDATE recordasset SET relative_path = '' WHERE relative_path IS NULL")
    op.alter_column(
        "recordasset", "relative_path", existing_type=sa.VARCHAR(), nullable=False
    )
    op.drop_column("recordasset", "data")
    op.drop_geospatial_column("recordasset", "geog")
    op.drop_column("recordasset", "asset_type")
    sa.Enum("DATA", "THUMBNAIL", "PREVIEW", name="assettype").drop(op.get_bind())
