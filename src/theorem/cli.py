"""Command-line entry: run a .thm file or an interactive REPL against a db path."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .engine.storage import Store, StoreLocked
from .ingest.bulk import LoadError, load_edges, load_nodes
from .ingest.extract import extract
from .ingest.normalize import IngestError, normalize
from .ingest.playbook import compile_playbook
from .ingest.runners import RunnerError, get_runner
from .ingest.stage import stage
from .parser import ParseError
from .schema import Schema
from .session import Session
from .verifier import VerifyError


def _add_schema_arg(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--schema",
        choices=["demo", "base"],
        default="demo",
        help="demo: the tutorial's supply-chain classes. base: entity and "
        "the document classes only, to derive your own from.",
    )


def _schema_for(name: str) -> Schema:
    return Schema.supply_chain() if name == "demo" else Schema()


def _handle_ingest(argv: list[str]) -> int:
    """Handle theorem ingest subcommand."""
    ap = argparse.ArgumentParser(prog="theorem ingest")
    ap.add_argument("file", help="file to ingest")
    ap.add_argument("--db", default=".theorem-db", help="database directory")
    _add_schema_arg(ap)
    ap.add_argument(
        "--extract", action="store_true", help="run extraction after staging"
    )
    ap.add_argument("--agent", default="claude", help="agent runner name")
    ap.add_argument(
        "--budget", type=int, default=50000, help="token budget for extraction"
    )
    args = ap.parse_args(argv)

    try:
        session = Session(Path(args.db), _schema_for(args.schema))
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


def _handle_load(argv: list[str]) -> int:
    """Bulk-load a CSV or JSONL file into a class or an edge type."""
    ap = argparse.ArgumentParser(
        prog="theorem load",
        description="Load rows into an existing class or edge type. The "
        "schema must already declare it; nothing is inferred.",
    )
    ap.add_argument("file", help="a .csv or .jsonl file")
    ap.add_argument("--db", default=".theorem-db", help="database directory")
    _add_schema_arg(ap)
    ap.add_argument("--class", dest="cls", help="class to load one node per row into")
    ap.add_argument("--edge", help="edge type to load one edge per row into")
    ap.add_argument(
        "--role",
        action="append",
        default=[],
        metavar="ROLE=COLUMN",
        help="which column names the node at this role (once per role)",
    )
    args = ap.parse_args(argv)
    if bool(args.cls) == bool(args.edge):
        print("error: give exactly one of --class or --edge", file=sys.stderr)
        return 1

    try:
        session = Session(Path(args.db), _schema_for(args.schema))
    except StoreLocked as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    try:
        if args.cls:
            receipt = load_nodes(session, Path(args.file), args.cls)
        else:
            columns = {}
            for pair in args.role:
                if "=" not in pair:
                    print(
                        f"error: --role wants ROLE=COLUMN, got {pair!r}",
                        file=sys.stderr,
                    )
                    return 1
                role, column = pair.split("=", 1)
                columns[role] = column
            receipt = load_edges(session, Path(args.file), args.edge, columns)
        print(receipt.render())
        return 0
    except (LoadError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        session.close()


def _handle_stats(argv: list[str]) -> int:
    """Report what a store holds and how close it is to the documented ceiling."""
    ap = argparse.ArgumentParser(
        prog="theorem stats",
        description="Node and edge counts, log and snapshot state, and the "
        "memory a store is using against the supported envelope.",
    )
    ap.add_argument("--db", default=".theorem-db", help="database directory")
    args = ap.parse_args(argv)

    path = Path(args.db)
    if not path.exists():
        print(f"error: no database at {path}", file=sys.stderr)
        return 1
    # A store being written by someone else is exactly when its numbers
    # are worth reading, so this does not take the lock.
    store = Store(path, lock=False)
    nodes, edges = len(store.nodes), len(store.edge_index)
    retired = sum(1 for n in store.nodes.values() if n.retired_at is not None)
    runs = sorted(path.glob("runs/run-*.json"))
    on_disk = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    print(f"store: {path}")
    print(f"  nodes:     {nodes:>12,}{f' ({retired:,} retired)' if retired else ''}")
    print(f"  edges:     {edges:>12,}")
    print(f"  classes:   {len(store.by_class):>12,}")
    print(f"  position:  {store.position:>12,}")
    print(f"  wal:       {store.wal_len():>12,} records")
    print(
        f"  snapshots: {len(runs):>12,}"
        + (f" (newest {runs[-1].name})" if runs else "")
    )
    print(f"  on disk:   {_human(on_disk):>12}")
    # 6.7 KB per node is the figure measured on the CypherBench politics
    # graph, and the one the supported envelope in the spec is derived
    # from. It is an estimate, and says so.
    print(f"  in memory: {_human(nodes * 6700):>12} (estimated at 6.7 KB/node)")
    if nodes:
        # Two thirds of RAM, not all of it: a query's binding table is
        # built on top of the graph, and a machine that is exactly full
        # is a machine that fails on the next question rather than on
        # the next node. This is the figure the spec's envelope quotes.
        capacity = int(0.66 * 32 * 1024**3) // 6700
        print(
            f"  a 32 GB machine holds about {capacity:,} nodes with room to "
            f"query them; this store is at {100 * nodes / capacity:.1f}% of that."
        )
    store.close()
    return 0


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} GB"


def _handle_playbook(argv: list[str]) -> int:
    """Handle theorem playbook subcommand."""
    ap = argparse.ArgumentParser(prog="theorem playbook")
    subparsers = ap.add_subparsers(dest="subcommand", required=True)

    compile_parser = subparsers.add_parser("compile", help="compile a playbook")
    compile_parser.add_argument("file", help="playbook markdown file")
    compile_parser.add_argument(
        "--db", default=".theorem-db", help="database directory"
    )
    _add_schema_arg(compile_parser)
    compile_parser.add_argument("--agent", default="claude", help="agent runner name")
    compile_parser.add_argument(
        "--unhinged", action="store_true", help="apply without confirmation"
    )

    args = ap.parse_args(argv)

    if args.subcommand == "compile":
        try:
            session = Session(Path(args.db), _schema_for(args.schema))
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

    if argv and argv[0] in ("ingest", "playbook", "load", "stats"):
        subcommand = argv[0]
        if subcommand == "ingest":
            return _handle_ingest(argv[1:])
        elif subcommand == "playbook":
            return _handle_playbook(argv[1:])
        elif subcommand == "load":
            return _handle_load(argv[1:])
        elif subcommand == "stats":
            return _handle_stats(argv[1:])

    ap = argparse.ArgumentParser(prog="theorem")
    ap.add_argument("file", nargs="?", help="a .thm program to run")
    ap.add_argument("--db", default=".theorem-db", help="database directory")
    _add_schema_arg(ap)
    ap.add_argument("--repl", action="store_true", help="interactive session")
    args = ap.parse_args(argv)

    try:
        session = Session(Path(args.db), _schema_for(args.schema))
    except StoreLocked as e:
        # A held database is an operator problem, not a bug: say what is
        # wrong on one line rather than unwinding a traceback at them.
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.file:
        print(session.run(Path(args.file).read_text()))
        session.close()
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
        session.close()
        return 0
    session.close()
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
