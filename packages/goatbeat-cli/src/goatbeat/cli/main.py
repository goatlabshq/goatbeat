import argparse
import sys
from collections.abc import Callable, Sequence
from typing import Final

from goatbeat.cli import commands
from goatbeat.cli.environment import Environment, open_environment
from goatbeat.cli.logs import configure_logging, is_database_unavailable
from goatbeat.core.errors import ConfigurationError, StoreUnavailableError

CONFIGURATION_ERROR: Final = 3
STORE_UNAVAILABLE: Final = 4
UNEXPECTED_ERROR: Final = 5
LOG_LEVELS: Final = ("DEBUG", "INFO", "WARNING", "ERROR")

type Handler = Callable[[Environment, argparse.Namespace], int]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="goatbeat", description=__doc__)
    root.add_argument("--app", help="module:attribute of a GoatbeatApp (or GOATBEAT_APP)")
    root.add_argument("--log-level", choices=LOG_LEVELS, default="INFO")
    root.add_argument("--log-format", choices=("text", "json"), default="text")
    sub = root.add_subparsers(dest="command", required=True)

    scheduler = sub.add_parser("scheduler", help="run the scheduler until SIGTERM")
    scheduler.add_argument("--once", action="store_true", help="run one tick and exit")
    scheduler.add_argument("--metrics-port", type=int, help="serve Prometheus metrics")
    scheduler.set_defaults(handler=_scheduler)

    status = sub.add_parser("status", help="show the leader and schedules")
    status.add_argument("--json", action="store_true", help="machine-readable output")
    status.set_defaults(handler=_status)

    doctor = sub.add_parser("doctor", help="check the setup")
    doctor.add_argument("--json", action="store_true", help="machine-readable output")
    doctor.set_defaults(handler=_doctor)

    migrate = sub.add_parser("migrate", help="create or upgrade the database schema")
    migrate.set_defaults(handler=_migrate)

    schedule = sub.add_parser("schedule", help="inspect and manage schedules")
    actions = schedule.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list", help="publish code schedules and list them")
    listing.add_argument("--json", action="store_true", help="machine-readable output")
    listing.set_defaults(handler=_list)
    run = actions.add_parser("run", help="ask the leader to run a schedule now")
    run.add_argument("name")
    run.set_defaults(handler=_run)
    prune = actions.add_parser("prune", help="disable code schedules no longer declared")
    prune.set_defaults(handler=_prune)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    handler: Handler = arguments.handler
    configure_logging(arguments.log_level, as_json=arguments.log_format == "json")
    try:
        with open_environment(arguments.app) as environment:
            return handler(environment, arguments)
    except ConfigurationError as error:
        sys.stderr.write(f"goatbeat: configuration error: {error}\n")
        return CONFIGURATION_ERROR
    except StoreUnavailableError as error:
        sys.stderr.write(f"goatbeat: store unavailable: {error}\n")
        return STORE_UNAVAILABLE
    except commands.CommandFailedError as error:
        sys.stderr.write(f"goatbeat: {error}\n")
        return commands.CHECK_FAILED
    except Exception as error:
        if is_database_unavailable(error):
            sys.stderr.write(f"goatbeat: store unavailable: {error}\n")
            return STORE_UNAVAILABLE
        sys.stderr.write(f"goatbeat: unexpected error: {type(error).__name__}: {error}\n")
        return UNEXPECTED_ERROR


def _scheduler(environment: Environment, arguments: argparse.Namespace) -> int:
    return commands.run_scheduler(
        environment, once=arguments.once, metrics_port=arguments.metrics_port
    )


def _status(environment: Environment, arguments: argparse.Namespace) -> int:
    return commands.status(environment, as_json=bool(arguments.json))


def _doctor(environment: Environment, arguments: argparse.Namespace) -> int:
    return commands.doctor(environment, as_json=bool(arguments.json))


def _migrate(environment: Environment, arguments: argparse.Namespace) -> int:
    del arguments
    return commands.migrate(environment)


def _list(environment: Environment, arguments: argparse.Namespace) -> int:
    return commands.list_schedules(environment, as_json=bool(arguments.json))


def _run(environment: Environment, arguments: argparse.Namespace) -> int:
    return commands.run_now(environment, str(arguments.name))


def _prune(environment: Environment, arguments: argparse.Namespace) -> int:
    del arguments
    return commands.prune(environment)


if __name__ == "__main__":
    raise SystemExit(main())
