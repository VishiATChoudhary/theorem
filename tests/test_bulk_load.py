"""Getting data in without writing it a row at a time.

The document pipeline stages a file and has an agent extract from it,
which is right for a PDF and wrong for a table whose columns are already
known. A language nobody can load their existing data into is a language
nobody uses.
"""

import pytest

from theorem.cli import main
from theorem.ingest.bulk import LoadError, load_edges, load_nodes
from theorem.schema import Schema
from theorem.session import Session
from theorem.verifier import VerifyError


@pytest.fixture
def sess(tmp_path):
    s = Session(tmp_path / "db", Schema.supply_chain())
    yield s
    s.close()


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_a_csv_becomes_nodes(sess, tmp_path):
    f = write(
        tmp_path,
        "parts.csv",
        "name,unit_cost\nBattery cell,12.5\nAnode,0.4\n",
    )
    receipt = load_nodes(sess, f, "part")
    assert receipt.written == 2
    out = sess.run("find part as p\nreturn p.name order by p.name")
    assert "Anode" in out and "Battery cell" in out


def test_types_come_from_the_schema(sess, tmp_path):
    f = write(tmp_path, "parts.csv", "name,unit_cost\nAnode,0.4\n")
    load_nodes(sess, f, "part")
    node = next(iter(sess.store.nodes.values()))
    assert node.props["unit_cost"] == 0.4  # a float, not the string "0.4"


def test_a_value_of_the_wrong_type_stops_the_load(sess, tmp_path):
    f = write(tmp_path, "parts.csv", "name,unit_cost\nAnode,cheap\n")
    with pytest.raises(LoadError) as e:
        load_nodes(sess, f, "part")
    assert "not float" in str(e.value)
    assert not sess.store.nodes  # nothing was written


def test_an_undeclared_column_stops_the_load(sess, tmp_path):
    f = write(tmp_path, "parts.csv", "name,colour\nAnode,black\n")
    with pytest.raises(LoadError) as e:
        load_nodes(sess, f, "part")
    assert "colour" in str(e.value)
    assert "Nothing was written" in str(e.value)
    assert not sess.store.nodes


def test_an_unknown_class_says_what_is_known(sess, tmp_path):
    f = write(tmp_path, "x.csv", "name\nA\n")
    with pytest.raises(LoadError) as e:
        load_nodes(sess, f, "widget")
    assert "derive class" in str(e.value)
    assert "supplier" in str(e.value)


def test_jsonl_works_too(sess, tmp_path):
    f = write(
        tmp_path,
        "parts.jsonl",
        '{"name": "Anode", "unit_cost": 0.4}\n{"name": "Cathode", "unit_cost": 0.6}\n',
    )
    assert load_nodes(sess, f, "part").written == 2


def test_an_empty_cell_leaves_the_property_unset(sess, tmp_path):
    f = write(tmp_path, "parts.csv", "name,unit_cost\nAnode,\n")
    load_nodes(sess, f, "part")
    node = next(iter(sess.store.nodes.values()))
    assert "unit_cost" not in node.props


# ---- edges ------------------------------------------------------------


@pytest.fixture
def loaded(sess, tmp_path):
    load_nodes(
        sess,
        write(tmp_path, "parts.csv", "name,unit_cost\nAnode,0.4\nCathode,0.6\n"),
        "part",
    )
    load_nodes(
        sess,
        write(tmp_path, "sups.csv", "name,country\nVoltaChem,DE\nIonix,KR\n"),
        "supplier",
    )
    return sess


def test_edges_resolve_endpoints_by_name(loaded, tmp_path):
    f = write(
        tmp_path,
        "links.csv",
        "part,supplier\nAnode,VoltaChem\nCathode,Ionix\n",
    )
    receipt = load_edges(
        loaded, f, "supplied_by", {"item": "part", "source": "supplier"}
    )
    assert receipt.written == 2
    out = loaded.run(
        'find part where name = "Anode" as p\n'
        "follow p supplied_by source as s\nreturn s.name"
    )
    assert "VoltaChem" in out


def test_edge_properties_load(loaded, tmp_path):
    f = write(
        tmp_path,
        "links.csv",
        "part,supplier,start_year\nAnode,VoltaChem,2019\n",
    )
    load_edges(loaded, f, "supplied_by", {"item": "part", "source": "supplier"})
    out = loaded.run(
        "find part as p\n"
        "follow p supplied_by source as s where via.start_year = 2019\n"
        "return p.name"
    )
    assert "Anode" in out


def test_a_missing_endpoint_skips_its_row_and_says_so(loaded, tmp_path):
    f = write(
        tmp_path,
        "links.csv",
        "part,supplier\nAnode,VoltaChem\nGhost,Ionix\n",
    )
    receipt = load_edges(
        loaded, f, "supplied_by", {"item": "part", "source": "supplier"}
    )
    assert receipt.written == 1
    assert "Ghost" in receipt.render()


def test_a_missing_role_is_refused_before_anything_is_written(loaded, tmp_path):
    f = write(tmp_path, "links.csv", "part\nAnode\n")
    with pytest.raises(LoadError) as e:
        load_edges(loaded, f, "supplied_by", {"item": "part"})
    assert "source" in str(e.value)


def test_an_ambiguous_name_is_an_error_not_a_coin_flip(sess, tmp_path):
    load_nodes(
        sess,
        write(tmp_path, "sups.csv", "name,country\nVoltaChem,DE\nVoltaChem,KR\n"),
        "supplier",
    )
    load_nodes(sess, write(tmp_path, "p.csv", "name,unit_cost\nAnode,0.4\n"), "part")
    f = write(tmp_path, "links.csv", "part,supplier\nAnode,VoltaChem\n")
    receipt = load_edges(sess, f, "supplied_by", {"item": "part", "source": "supplier"})
    assert receipt.written == 0
    assert "merge them first" in receipt.render()


# ---- the CLI ----------------------------------------------------------


def test_the_cli_loads_nodes_and_edges(tmp_path, capsys):
    db = tmp_path / "db"
    parts = write(tmp_path, "parts.csv", "name,unit_cost\nAnode,0.4\n")
    sups = write(tmp_path, "sups.csv", "name,country\nVoltaChem,DE\n")
    links = write(tmp_path, "links.csv", "part,supplier\nAnode,VoltaChem\n")
    assert main(["load", str(parts), "--db", str(db), "--class", "part"]) == 0
    assert main(["load", str(sups), "--db", str(db), "--class", "supplier"]) == 0
    assert (
        main(
            [
                "load",
                str(links),
                "--db",
                str(db),
                "--edge",
                "supplied_by",
                "--role",
                "item=part",
                "--role",
                "source=supplier",
            ]
        )
        == 0
    )
    assert "loaded 1 edge" in capsys.readouterr().out


def test_the_cli_refuses_both_class_and_edge(tmp_path, capsys):
    f = write(tmp_path, "x.csv", "name\nA\n")
    code = main(
        [
            "load",
            str(f),
            "--db",
            str(tmp_path / "db"),
            "--class",
            "part",
            "--edge",
            "uses",
        ]
    )
    assert code == 1
    assert "exactly one" in capsys.readouterr().err


def test_the_cli_reports_a_load_error_without_a_traceback(tmp_path, capsys):
    f = write(tmp_path, "parts.csv", "name,colour\nAnode,black\n")
    code = main(["load", str(f), "--db", str(tmp_path / "db"), "--class", "part"])
    assert code == 1
    assert "colour" in capsys.readouterr().err


# ---- the schema the CLI opens with ------------------------------------


def test_the_cli_can_open_a_database_without_the_demo_classes(tmp_path, capsys):
    """A production user's schema is their own; the demo supply chain
    must not be the only thing the CLI can open a database with."""
    program = tmp_path / "s.thm"
    program.write_text(
        "derive class widget from entity with {sku: str}\n"
        'assert widget {name: "W1", sku: "A-1"} as w\n'
        "find widget as w2\nreturn w2.sku\n"
    )
    code = main([str(program), "--db", str(tmp_path / "db"), "--schema", "base"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "A-1" in out
    assert "product" not in out


def test_the_package_exports_what_an_application_needs():
    import theorem

    for name in ("Session", "Schema", "Store", "StoreLocked", "limits", "parse"):
        assert hasattr(theorem, name), name
    assert theorem.__version__


def test_the_loader_accepts_inherited_properties(tmp_path):
    """A class derived from `entity` inherits `name`, and every file has
    that column. Checking only the class's own props rejected all of them."""
    s = Session(tmp_path / "db", Schema())
    s.run("derive class factory from entity with {country: str}")
    f = write(tmp_path, "f.csv", "name,country\nWolfsburg,DE\n")
    assert load_nodes(s, f, "factory").written == 1
    assert "Wolfsburg" in s.run("find factory as f\nreturn f.name")
    s.close()


def test_rows_returns_values_and_raises_on_error(tmp_path):
    """`run` renders for a reader; a program wants the values, and an
    exception it can catch rather than an error it must remember to look
    for in a string."""
    s = Session(tmp_path / "db", Schema.supply_chain())
    load_nodes(s, write(tmp_path, "p.csv", "name,unit_cost\nAnode,0.4\n"), "part")
    assert s.rows("find part as p\nreturn p.name") == [["Anode"]]
    with pytest.raises(VerifyError):
        s.rows("find part as p\nreturn p.colour")
    s.close()
