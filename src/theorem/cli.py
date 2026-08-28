"""Command-line entry: run a .thm file or an interactive REPL against a db path."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .ingest.extract import extract
from .ingest.normalize import IngestError, normalize
from .ingest.playbook import compile_playbook
from .ingest.runners import RunnerError, get_runner
from .ingest.stage import stage
from .parser import ParseError
from .schema import Schema
from .session import Session
from .verifier import VerifyError


def _handle_ingest(argv: list[str]) -> int:
    """Handle theorem ingest subcommand."""
    ap = argparse.ArgumentParser(prog="theorem ingest")
    ap.add_argument("file", help="file to ingest")
    ap.add_argument("--db", default=".theorem-db", help="database directory")
    ap.add_argument(
        "--extract", action="store_true", help="run extraction after staging"
    )
    ap.add_argument("--agent", default="claude", help="agent runner name")
    ap.add_argument(
        "--budget", type=int, default=50000, help="token budget for extraction"
    )
    args = ap.parse_args(argv)

    try:
        session = Session(Path(args.db), Schema.supply_chain())
        file_path = Path(args.file)
        raw = file_path.read_bytes()
        envelope = normalize(raw, file_path.name)
        stage_receipt = stage(session, envelope, file_path.name, raw)
        print(stage_receipt.render())

        if args.extract:
            try:
                runner = get_runner(args.agent)
            except RunnerError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            try:
                extract_receipt = extract(
                    session,
                    stage_receipt.doc_id,
                    runner,
                    budget=args.budget,
                    focus="",
                )
            except RunnerError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            print(extract_receipt.render())

        return 0
    except IngestError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _handle_playbook(argv: list[str]) -> int:
    """Handle theorem playbook subcommand."""
    ap = argparse.ArgumentParser(prog="theorem playbook")
    subparsers = ap.add_subparsers(dest="subcommand", required=True)

    compile_parser = subparsers.add_parser("compile", help="compile a playbook")
    compile_parser.add_argument("file", help="playbook markdown file")
    compile_parser.add_argument(
        "--db", default=".theorem-db", help="database directory"
    )
    compile_parser.add_argument("--agent", default="claude", help="agent runner name")
    compile_parser.add_argument(
        "--unhinged", action="store_true", help="apply without confirmation"
    )

    args = ap.parse_args(argv)

    if args.subcommand == "compile":
        try:
            session = Session(Path(args.db), Schema.supply_chain())
            runner = get_runner(args.agent)
        except RunnerError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

        try:

            def confirm_fn(text: str) -> bool:
                print(text)
                response = input("apply? [y/N] ")
                return response.lower() in ("y", "yes")

            playbook_receipt = compile_playbook(
                session,
                Path(args.file),
                runner,
                unhinged=args.unhinged,
                confirm=confirm_fn,
            )
            print(playbook_receipt.render())
            return 0 if not playbook_receipt.aborted else 1
        except (IngestError, ParseError, VerifyError, RuntimeError, RunnerError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    ap.print_help()
    return 1


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] in ("ingest", "playbook"):
        subcommand = argv[0]
        if subcommand == "ingest":
            return _handle_ingest(argv[1:])
        elif subcommand == "playbook":
            return _handle_playbook(argv[1:])

    ap = argparse.ArgumentParser(prog="theorem")
    ap.add_argument("file", nargs="?", help="a .thm program to run")
    ap.add_argument("--db", default=".theorem-db", help="database directory")
    ap.add_argument("--repl", action="store_true", help="interactive session")
    args = ap.parse_args(argv)

    session = Session(Path(args.db), Schema.supply_chain())
    if args.file:
        print(session.run(Path(args.file).read_text()))
        return 0
    if args.repl:
        print(
            "theorem v0. one statement per line; blank line to execute a block; ctrl-d to exit."
        )
        block: list[str] = []
        try:
            for line in sys.stdin:
                if line.strip():
                    block.append(line.rstrip("\n"))
                    continue
                if block:
                    print(session.run("\n".join(block)))
                    block = []
        except KeyboardInterrupt:
            pass
        if block:
            print(session.run("\n".join(block)))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
