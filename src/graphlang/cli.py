"""Command-line entry: run a .gl file or an interactive REPL against a db path."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .schema import Schema
from .session import Session


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="graphlang")
    ap.add_argument("file", nargs="?", help="a .gl program to run")
    ap.add_argument("--db", default=".graphlang-db", help="database directory")
    ap.add_argument("--repl", action="store_true", help="interactive session")
    args = ap.parse_args(argv)

    session = Session(Path(args.db), Schema.supply_chain())
    if args.file:
        print(session.run(Path(args.file).read_text()))
        return 0
    if args.repl:
        print("graphlang v0. one statement per line; blank line to execute a block; ctrl-d to exit.")
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
