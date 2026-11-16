from alembic import context
from app.database import Base, engine
from app import models  # noqa: F401

if context.is_offline_mode():
    context.configure(url=str(engine.url), target_metadata=Base.metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            # Start a real transaction before SQLite executes the first DDL statement.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
