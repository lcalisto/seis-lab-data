import dataclasses
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Annotated

from rich.padding import Padding
from rich.panel import Panel
import typer

from .. import config
from ..db.queries import (
    projects as project_queries,
    surveymissions as mission_queries,
)
from ..schemas import identifiers
from ..tasks import (
    broker,
    previews as preview_tasks,
)
from . import utils
from .asynctyper import AsyncTyper
from .bootstrapapp import app as bootstrap_app
from .dbapp import app as db_app
from .devapp import app as dev_app
from .translationsapp import app as translations_app

logger = logging.getLogger(__name__)
app = AsyncTyper()
app.add_typer(translations_app, name="translations")
app.add_typer(db_app, name="db")
app.add_typer(dev_app, name="dev")
app.add_typer(bootstrap_app, name="bootstrap")


@app.callback()
def base_callback(ctx: typer.Context) -> None:
    """SeisLabData command line interface"""
    context = config.get_cli_context()
    broker.setup_broker(context.settings)
    config.configure_logging(context)
    ctx.obj = {"main": context}


@app.command()
def run_worker(
    ctx: typer.Context,
    queues: Annotated[
        list[str] | None,
        typer.Option(
            "--queue",
            help="Queue to consume, repeatable. All queues are consumed if omitted.",
        ),
    ] = None,
    processes: Annotated[
        int | None,
        typer.Option(
            min=1,
            help=(
                "Number of worker processes. Defaults to 1 in debug mode, otherwise "
                "to dramatiq's default of one per CPU core."
            ),
        ),
    ] = None,
    threads: Annotated[
        int | None,
        typer.Option(
            min=1,
            help=(
                "Number of threads per worker process. Defaults to 1 in debug mode, "
                "otherwise to dramatiq's default of 8."
            ),
        ),
    ] = None,
) -> None:
    """Start a dramatiq worker.

    In debug mode the worker also reloads on source code changes.
    """
    context: config.SeisLabDataCliContext = ctx.obj["main"]
    panel = Panel(
        "SeisLabData worker",
        title="seis-lab-data",
        expand=False,
        padding=(1, 2),
        style="green",
    )
    context.status_console.print(Padding(panel, 1))
    dramatiq_args = [
        "dramatiq",
        "--skip-logging",
        "seis_lab_data.tasks.broker:setup_broker",
    ]
    if context.settings.debug:
        dramatiq_args.extend(
            [
                f"--watch={Path(__file__).parents[1]}",
                "--watch-exclude=__pycache__/*",
            ]
        )
        processes = processes or 1
        threads = threads or 1
    if processes is not None:
        dramatiq_args.append(f"--processes={processes}")
    if threads is not None:
        dramatiq_args.append(f"--threads={threads}")
    if queues:
        dramatiq_args.extend(["--queues", *queues])
    sys.stdout.flush()
    sys.stderr.flush()
    context.status_console.print(
        f"Starting dramatiq worker with args: {dramatiq_args=}"
    )
    os.execvp("dramatiq", dramatiq_args)


@app.command()
def run_web_server(ctx: typer.Context):
    """Run the uvicorn server"""
    # NOTE: we explicitly do not use uvicorn's programmatic running abilities here
    # because they do not work correctly when called outside an
    # `if __name__ == __main__` guard and when using its debug features.
    # For more detail check:
    #
    # https://github.com/encode/uvicorn/issues/1045
    #
    # This solution works well both in development (where we want to use reload)
    # and in production, as using os.execvp is actually similar to just running
    # the standard `uvicorn` cli command (which is what uvicorn docs recommend).
    context: config.SeisLabDataCliContext = ctx.obj["main"]
    uvicorn_args = [
        "uvicorn",
        "seis_lab_data.webapp.app:create_app",
        f"--port={context.settings.bind_port}",
        f"--host={context.settings.bind_host}",
        "--factory",
        "--access-log",
    ]
    if context.settings.debug:
        uvicorn_args.extend(
            [
                "--reload",
                f"--reload-dir={str(Path(__file__).parents[1])}",
                "--log-level=debug",
            ]
        )
    else:
        uvicorn_args.extend(
            [
                f"--workers={context.settings.num_web_worker_processes}",
                "--log-level=info",
            ]
        )
    if (log_config_file := context.settings.log_config_file) is not None:
        uvicorn_args.append(f"--log-config={str(log_config_file)}")
    if context.settings.public_url.startswith("https://"):
        uvicorn_args.extend(
            [
                "--forwarded-allow-ips=*",
                "--proxy-headers",
            ]
        )

    serving_str = (
        f"[dim]Serving at:[/dim] [link]http://{context.settings.bind_host}:"
        f"{context.settings.bind_port}[/link]\n\n"
        f"[dim]Public URL:[/dim] [link]{context.settings.public_url}[/link]\n\n"
    )
    panel = Panel(
        (
            f"{serving_str}\n\n"
            f"[dim]Running in [b]"
            f"{'development' if context.settings.debug else 'production'} mode[/b]"
        ),
        title="seis-lab-data",
        expand=False,
        padding=(1, 2),
        style="green",
    )
    context.status_console.print(Padding(panel, 1))
    sys.stdout.flush()
    sys.stderr.flush()
    os.execvp("uvicorn", uvicorn_args)


@app.async_command()
async def generate_thumbnails(
    ctx: typer.Context,
    admin_username: str | None = typer.Option(
        default="akadmin",
        help="Authentik username of the admin user to act as.",
    ),
    admin_user_id: str | None = typer.Option(
        default=None,
        help=(
            "Authentik sub (UUID) of the admin user to act as. Takes "
            "precedence over --admin-username."
        ),
    ),
) -> None:
    """Queue the thumbnail generation of every project and survey mission with a bbox

    Thumbnails are only generated when a bbox is set or changed.
    This fills them in for the bboxes which already existed before.
    """
    context: config.SeisLabDataCliContext = ctx.obj["main"]
    admin_user = await utils.resolve_admin_user(
        context.settings, admin_username, admin_user_id
    )
    raw_request_id = str(identifiers.RequestId(uuid.uuid4()))
    raw_initiator = json.dumps(dataclasses.asdict(admin_user))
    num_queued = 0
    async with context.settings.get_db_session_maker()() as session:
        for project in await project_queries.collect_all_projects(session):
            if project.bbox_4326 is not None:
                preview_tasks.generate_project_thumbnail.send(
                    raw_request_id=raw_request_id,
                    raw_project_id=str(project.id),
                    raw_initiator=raw_initiator,
                )
                num_queued += 1
            survey_missions = await mission_queries.collect_all_project_survey_missions(
                session, identifiers.ProjectId(project.id)
            )
            for survey_mission in survey_missions:
                if survey_mission.bbox_4326 is not None:
                    preview_tasks.generate_survey_mission_thumbnail.send(
                        raw_request_id=raw_request_id,
                        raw_survey_mission_id=str(survey_mission.id),
                        raw_initiator=raw_initiator,
                    )
                    num_queued += 1
    context.status_console.print(f"Queued {num_queued} thumbnails for generation")
