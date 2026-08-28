import pytest

from theorem.ingest.runners import CLIRunner, RunnerError, get_runner


def test_cli_runner_captures_stdout():
    r = CLIRunner(argv=["/bin/echo"])
    assert r.run("hello").strip() == "hello"


def test_cli_runner_error_on_failure():
    r = CLIRunner(argv=["/usr/bin/false"])
    with pytest.raises(RunnerError):
        r.run("x")


def test_get_runner_unknown():
    with pytest.raises(RunnerError, match="claude"):
        get_runner("clippy")
