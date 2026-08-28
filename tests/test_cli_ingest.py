from theorem.cli import main


def test_cli_ingest_stages_file(tmp_path, capsys):
    f = tmp_path / "n.md"
    f.write_text("# T\n\nsome text")
    rc = main(["ingest", str(f), "--db", str(tmp_path / "db")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "document" in out and "chunk" in out


def test_cli_legacy_repl_flag_still_parses(tmp_path):
    # legacy path: running a program file
    p = tmp_path / "p.thm"
    p.write_text("schema")
    assert main([str(p), "--db", str(tmp_path / "db")]) == 0
