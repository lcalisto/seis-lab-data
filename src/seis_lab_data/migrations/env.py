from logging.config import fileConfig

# DO NOT REMOVE - this import is needed in order to enjoy proper enum support
import alembic_postgresql_enum  # noqa

from sqlalchemy import create_engine
from alembic import context
from geoalchemy2 import alembic_helpers
from sqlmodel import SQLModel

from seis_lab_data import config as seis_lab_data_config

# this import is crucial for SQLModel.metadata to be populated
# with our models, do not remove!
from seis_lab_data.db import models  # noqa

seis_lab_data_settings = seis_lab_data_config.get_settings()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def include_name(name, type_, parent_names) -> bool:
    """Control which names to include in the autogeneration of migrations.

    This is used in order to exclude certain tables from being considered by alembic
    when generating migrations.
    More info:

     https://alembic.sqlalchemy.org/en/latest/autogenerate.html#omitting-table-names-from-the-autogenerate-process
    """
    if type_ == "table":
        return name in target_metadata.tables
    else:
        return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = seis_lab_data_settings.database_dsn.unicode_string()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_name=include_name,
        include_object=alembic_helpers.include_object,
        process_revision_directives=alembic_helpers.writer,
        render_item=alembic_helpers.render_item,
        # without it, a changed column default goes unnoticed by autogenerate
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = create_engine(seis_lab_data_settings.database_dsn.unicode_string())
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=alembic_helpers.include_object,
            include_name=include_name,
            process_revision_directives=alembic_helpers.writer,
            render_item=alembic_helpers.render_item,
            # without it, a changed column default goes unnoticed by autogenerate
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
