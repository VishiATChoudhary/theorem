"""The path a person actually takes to put this in production.

Every piece below is covered by a unit test somewhere. This runs them in
the order a new user runs them, in one database, because the failures
that matter are between the pieces: a schema that does not survive a
restart, a lock that is still held, a loader that writes something the
query path cannot read.
"""

import subprocess
import sys

import pytest

from theorem import Schema, Session, agent_prompt

SCHEMA = """derive class factory from entity with {country: str, opened: int}
derive class component from entity with {sku: str, grams: float}
derive edge assembles(plant: factory, part: component)
"""


def csv(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def db(tmp_path):
    return tmp_path / "prod-db"


def test_a_whole_deployment(db, tmp_path):
    from theorem.ingest.bulk import load_edges, load_nodes

    # 1. Start from the base schema and declare your own domain.
    with Session(db, Schema()) as s:
        out = s.run(SCHEMA)
        assert "error" not in out.lower(), out
        assert "product" not in s.schema.classes  # no demo classes

    # 2. Reopen. The schema a previous process derived is still there.
    with Session(db, Schema()) as s:
        assert "factory" in s.schema.classes
        assert "assembles" in s.schema.edges

        # 3. Load the data you already have.
        load_nodes(
            s,
            csv(
                tmp_path,
                "factories.csv",
                "name,country,opened\nWolfsburg,DE,1938\nToyota City,JP,1959\n",
            ),
            "factory",
        )
        load_nodes(
            s,
            csv(
                tmp_path,
                "components.csv",
                "name,sku,grams\nAxle,AX-1,4200\nSeat,ST-9,11000\nBolt,BO-3,12\n",
            ),
            "component",
        )
        receipt = load_edges(
            s,
            csv(
                tmp_path,
                "bom.csv",
                "factory,component\n"
                "Wolfsburg,Axle\nWolfsburg,Seat\nWolfsburg,Bolt\nToyota City,Axle\n",
            ),
            "assembles",
            {"plant": "factory", "part": "component"},
        )
        assert receipt.written == 4

        # 4. Ask something that needs the whole pipeline.
        out = s.run(
            "find factory as f\n"
            "follow f assembles part as c\n"
            "group by f as g\n"
            "count distinct g.c as n\n"
            "keep g where n > 2\n"
            "return f.name, n"
        )
        assert "Wolfsburg" in out and "Toyota City" not in out

        # 5. A mistake is refused whole, with the schema's own words.
        bad = s.run("find factory as f\nreturn f.contry")
        assert "country" in bad and "nothing was executed" in bad.lower()

        # 6. The prompt an agent would be given knows about this schema.
        prompt = agent_prompt(s.schema, "which factories assemble an axle?", s.store)
        assert "assembles" in prompt and "factory" in prompt

    # 7. Everything survives a restart, including what the loader wrote.
    with Session(db, Schema()) as s:
        out = s.run(
            'find component where sku = "AX-1" as c\n'
            "follow c assembles plant as f\n"
            "return f.name order by f.name"
        )
        assert "Wolfsburg" in out and "Toyota City" in out


def test_a_second_process_cannot_corrupt_it(db):
    with Session(db, Schema()) as s:
        s.run(SCHEMA)
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys\n"
                "from theorem import Schema, Session, StoreLocked\n"
                "try:\n"
                "    Session(sys.argv[1], Schema())\n"
                "except StoreLocked as e:\n"
                "    print('refused')\n",
                str(db),
            ],
            capture_output=True,
            text=True,
        )
        assert probe.stdout.strip() == "refused", probe.stderr


def test_the_lock_is_released_when_the_session_closes(db):
    with Session(db, Schema()) as s:
        s.run(SCHEMA)
    with Session(db, Schema()) as s:
        assert "factory" in s.schema.classes


def test_the_cli_and_the_library_share_one_database(db, tmp_path):
    from theorem.cli import main

    program = tmp_path / "schema.thm"
    program.write_text(SCHEMA)
    assert main([str(program), "--db", str(db), "--schema", "base"]) == 0

    rows = csv(tmp_path, "f.csv", "name,country,opened\nWolfsburg,DE,1938\n")
    assert main(["load", str(rows), "--db", str(db), "--class", "factory"]) == 0

    with Session(db, Schema()) as s:
        out = s.run("find factory as f\nreturn f.name")
        assert "Wolfsburg" in out


def test_a_runaway_query_cannot_take_the_process_down(db):
    """The ceiling is on by default; a caller does not have to know."""
    from theorem import ExecError, limits
    from theorem.ingest.bulk import load_edges, load_nodes

    with Session(db, Schema()) as s:
        s.run(SCHEMA)
        n = 40
        load_nodes(
            s,
            _tmpcsv(
                s,
                "name,country,opened\n" + "".join(f"f{i},DE,2000\n" for i in range(n)),
            ),
            "factory",
        )
        load_nodes(
            s,
            _tmpcsv(
                s, "name,sku,grams\n" + "".join(f"c{i},S{i},1.0\n" for i in range(n))
            ),
            "component",
        )
        load_edges(
            s,
            _tmpcsv(
                s,
                "factory,component\n"
                + "".join(f"f{i},c{j}\n" for i in range(n) for j in range(n)),
            ),
            "assembles",
            {"plant": "factory", "part": "component"},
        )
        with limits(max_rows=500):
            with pytest.raises(ExecError) as e:
                s.rows(
                    "find factory as f\n"
                    "follow f assembles part as c\n"
                    "follow c assembles plant as f2\n"
                    "return f2.name"
                )
        assert "500" in str(e.value)


def _tmpcsv(session, text: str):
    """A CSV next to the database, so the fixture needs no extra plumbing."""
    path = session.store.path / f"tmp-{abs(hash(text))}.csv"
    path.write_text(text, encoding="utf-8")
    return path
