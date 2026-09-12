import logging
import os
import sys
from pathlib import Path

from rich.padding import Padding
from rich.panel import Panel
import typer

from .. import config
from ..tasks import broker
from .bootstrapapp import app as bootstrap_app
from .dbapp import app as db_app
from .devapp import app as dev_app
from .mainapp import app as main_app
from .translationsapp import app as translations_app

logger = logging.getLogger(__name__)
app = typer.Typer()
app.add_typer(translations_app, name="translations")
app.add_typer(db_app, name="db")
app.add_typer(main_app, name="main")
app.add_typer(dev_app, name="dev")
app.add_typer(bootstrap_app, name="bootstrap")


@app.callback()
def base_callback(ctx: typer.Context) -> None:
    """SeisLabData command line interface"""
    context = config.get_cli_context()
    broker.setup_broker(context.settings)
    config.configure_logging(context)
    ctx.obj = {"main": context}


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def run_processing_worker(ctx: typer.Context) -> None:
    """Start a processing worker"""
    context: config.SeisLabDataCliContext = ctx.obj["main"]
    panel = Panel(
        "SeisLabData processing worker",
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
                "--processes=1",
                "--threads=1",
                f"--watch={Path(__file__).parents[1]}",
                "--watch-exclude=__pycache__/*",
            ]
        )
    # extra args are passed straight to dramatiq, which is how a worker gets
    # pinned to a queue (`run-processing-worker --queues previews`)
    dramatiq_args.extend(ctx.args)
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
