"""What a backend task definition needs to reach Aurora, checked at synth (#78).

Both task definitions -- the API service (``fargate_service_stack.py``) and the
one-shot migration task (``migration_task_stack.py``) -- used to be built with
no database host at all, so the application fell back to ``localhost``: the
entry point's ``pg_isready`` loop waited DB_WAIT_TIMEOUT against the container
itself and exited 1, and the ALB health check (``/health`` runs the database
check) never passed. Nothing refused that at synth, so it would have been found
by the first deployment.

So the stacks refuse, at synth, to be built without a host or without the
credentials secret. The host is meant to be the database stack's writer
endpoint (``EnhancedDatabaseStack.writer_host``), which synthesises to an
``Fn::ImportValue``; ``infrastructure/tests/test_database_wiring.py`` asserts
exactly that on the staging and prod templates. The literal check below is the
cheap half: it stops the one literal that is always wrong.
"""

from __future__ import annotations

from aws_cdk import Token

#: Hosts that inside a Fargate task mean "this container", never a database.
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def require_database(stack_name: str, db_host, db_credentials) -> None:
    """Raise ``ValueError`` unless the task can be told where Aurora is."""
    if db_host is None or (
        not Token.is_unresolved(db_host) and not str(db_host).strip()
    ):
        raise ValueError(
            f"{stack_name} requires db_host: the Aurora writer endpoint "
            "(app.py passes database_stack.writer_host). Without it the "
            "application connects to localhost and the task never becomes "
            "healthy (#78)."
        )
    if not Token.is_unresolved(db_host) and str(db_host).strip().lower() in _LOOPBACK:
        raise ValueError(
            f"{stack_name}: db_host={db_host!r} is the container itself, not a "
            "database. Pass the Aurora writer endpoint (database_stack.writer_host)."
        )
    if db_credentials is None:
        raise ValueError(
            f"{stack_name} requires db_credentials: the secret Aurora generated "
            "its master credentials into (app.py passes "
            "database_stack.db_credentials). POSTGRES_USER and POSTGRES_PASSWORD "
            "are read from its `username` and `password` fields."
        )
