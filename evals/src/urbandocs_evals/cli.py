"""`urbandocs-evals` entry point (#85): `upload-dataset` and `run`."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from langsmith import Client

from urbandocs_evals.config import Config, ConfigError
from urbandocs_evals.dataset import upload_dataset
from urbandocs_evals.run import run_experiment

DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"


def _cmd_upload_dataset(args: argparse.Namespace) -> int:
    client = Client()
    dataset_name = args.dataset_name
    message = upload_dataset(client, dataset_name, args.docs_dir, recreate=args.recreate)
    print(message)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    client = Client()
    results = asyncio.run(
        run_experiment(
            cfg,
            client,
            concurrency=args.concurrency,
            experiment_prefix=args.experiment_prefix,
        )
    )
    print(f"experiment done: {results}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="urbandocs-evals")
    sub = parser.add_subparsers(dest="command", required=True)

    upload = sub.add_parser(
        "upload-dataset",
        help="upload docs/eval-questions.csv + eval-answers.csv as a LangSmith Dataset",
    )
    upload.add_argument(
        "--docs-dir", type=Path, default=DOCS_DIR, help="directory holding the gold-set CSVs"
    )
    upload.add_argument(
        "--dataset-name",
        default="urbandocs-gold-set",
        help="LangSmith dataset name (default: urbandocs-gold-set)",
    )
    upload.add_argument(
        "--recreate",
        action="store_true",
        help="delete and rebuild the dataset if it already exists",
    )
    upload.set_defaults(func=_cmd_upload_dataset)

    run = sub.add_parser(
        "run", help="run the agent against the gold set as a LangSmith Experiment"
    )
    run.add_argument(
        "--concurrency", type=int, default=1, help="questions run concurrently (default: 1)"
    )
    run.add_argument(
        "--experiment-prefix",
        default="urbandocs-eval",
        help="LangSmith experiment name prefix (default: urbandocs-eval)",
    )
    run.set_defaults(func=_cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # evals/.env, local-dev convenience only -- see README
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
