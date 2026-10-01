"""`urbandocs-evals` entry point (#85): `upload-dataset` and `run`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from langfuse import Langfuse, get_client

from urbandocs_evals.config import Config, ConfigError, dataset_name_from_env
from urbandocs_evals.dataset import upload_dataset
from urbandocs_evals.run import run_experiment

DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"


def _cmd_upload_dataset(args: argparse.Namespace) -> int:
    client = Langfuse()
    # `--dataset-name` wins if passed; otherwise falls back to the same
    # `LANGFUSE_DATASET` env var `run` reads via `Config.from_env`, so the
    # two commands never point at different datasets by accident.
    dataset_name = args.dataset_name or dataset_name_from_env()
    message = upload_dataset(client, dataset_name, args.docs_dir)
    print(message)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    client = Langfuse()
    result = run_experiment(
        cfg,
        client,
        concurrency=args.concurrency,
        experiment_prefix=args.experiment_prefix,
        question_set=args.set,
    )
    print(result.format())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="urbandocs-evals")
    sub = parser.add_subparsers(dest="command", required=True)

    upload = sub.add_parser(
        "upload-dataset",
        help="sync docs/eval-questions.csv + eval-answers.csv into a Langfuse Dataset",
    )
    upload.add_argument(
        "--docs-dir", type=Path, default=DOCS_DIR, help="directory holding the gold-set CSVs"
    )
    upload.add_argument(
        "--dataset-name",
        default=None,
        help=(
            "Langfuse dataset name (default: $LANGFUSE_DATASET, "
            "falling back to urbandocs-gold-set)"
        ),
    )
    upload.set_defaults(func=_cmd_upload_dataset)

    run = sub.add_parser(
        "run", help="run the agent against the gold set as a Langfuse Experiment"
    )
    run.add_argument(
        "--concurrency", type=int, default=1, help="questions run concurrently (default: 1)"
    )
    run.add_argument(
        "--experiment-prefix",
        default="urbandocs-eval",
        help="Langfuse experiment name (default: urbandocs-eval)",
    )
    run.add_argument(
        "--set",
        choices=["easy", "complex"],
        default=None,
        help="run only this question set (default: the whole gold set)",
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
    finally:
        # Short-lived process: export buffered spans and scores before exit.
        get_client().flush()


if __name__ == "__main__":
    sys.exit(main())
