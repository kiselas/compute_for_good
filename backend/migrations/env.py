from alembic import context
from computeforgood.db import Base, engine
from computeforgood import models  # noqa: F401

if context.is_offline_mode():
    from computeforgood.config import settings
    context.configure(url=settings.database_url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
