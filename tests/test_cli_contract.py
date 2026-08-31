"""What a shell, a Makefile and a CI step are entitled to assume.

A CLI that prints an error and exits 0 is the same silent failure this
language exists to prevent, moved one layer out: `theorem build.thm && deploy`
would deploy on a refused program. These pin the exit codes, the default
schema, and the canonical printer.
"""

from theorem.cli import main


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_a_refused_program_exits_non_zero(tmp_path, capsys):
    program = write(tmp_path, "bad.thm", "find widget as w\nreturn w.name\n")
    code = main([str(program), "--db", str(tmp_path / "db")])
    captured = capsys.readouterr()
    assert code == 1
    assert "unknown class" in captured.err
    assert "nothing was executed" in captured.err
    # One prefix, not two: the verifier's messages already lead with it.
    assert not captured.err.startswith("error: error:")


def test_a_program_that_works_exits_zero_and_prints_the_answer(tmp_path, capsys):
    program = write(
        tmp_path,
        "ok.thm",
        "derive class widget from entity with {sku: str}\n"
        'assert widget {name: "W1", sku: "A-1"} as w\n'
        "find widget as w2\nreturn w2.sku\n",
    )
    code = main([str(program), "--db", str(tmp_path / "db")])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "A-1" in out


def test_the_default_schema_is_the_users_own(tmp_path, capsys):
    """`supplier`, `part` and `product` are ordinary domain names. Shipping
    them by default collided with a real schema on the first try."""
    program = write(
        tmp_path,
        "s.thm",
        "derive class supplier from entity with {country: str}\n"
        "find supplier as s\nreturn s.name\n",
    )
    assert main([str(program), "--db", str(tmp_path / "db")]) == 0
    assert "already exists" not in capsys.readouterr().out


def test_the_demo_schema_is_still_reachable(tmp_path, capsys):
    program = write(tmp_path, "d.thm", "find product as p\nreturn p.name\n")
    code = main([str(program), "--db", str(tmp_path / "db"), "--schema", "demo"])
    assert code == 0, capsys.readouterr().out


def test_canonical_prints_one_spelling_for_two_writings(tmp_path, capsys):
    a = write(
        tmp_path, "a.thm", 'find supplier where country = "DE" as s\nreturn s.name\n'
    )
    b = write(
        tmp_path, "b.thm", 'find supplier as s where country = "DE"\nreturn s.name\n'
    )
    assert main(["canonical", str(a)]) == 0
    first = capsys.readouterr().out
    assert main(["canonical", str(b)]) == 0
    assert capsys.readouterr().out == first


def test_canonical_needs_no_database(tmp_path, capsys):
    """It parses and prints; nothing is opened, so no lock and no schema."""
    a = write(tmp_path, "a.thm", "find widget as w\nreturn w.name\n")
    assert main(["canonical", str(a)]) == 0
    assert "find widget as w" in capsys.readouterr().out
    assert not (tmp_path / ".theorem-db").exists()


def test_canonical_exits_non_zero_on_a_program_it_cannot_parse(tmp_path, capsys):
    bad = write(tmp_path, "bad.thm", "find\n")
    assert main(["canonical", str(bad)]) == 1
    assert "error:" in capsys.readouterr().err
