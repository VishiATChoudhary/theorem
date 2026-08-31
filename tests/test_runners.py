"""The agent runners, on every platform CI claims to support.

These used to name `/bin/echo` and `/usr/bin/false`, which do not exist
on Windows, so the matrix was red on a path that was not actually broken.
Spawning this interpreter works everywhere.
"""

import sys

import pytest

from theorem.ingest.runners import CLIRunner, RunnerError, get_runner

ECHO = [sys.executable, "-c", "import sys; print(sys.argv[1], end='')"]
FAIL = [sys.executable, "-c", "raise SystemExit(1)"]


def test_cli_runner_captures_stdout():
    assert CLIRunner(argv=ECHO).run("hello") == "hello"


def test_cli_runner_error_on_failure():
    with pytest.raises(RunnerError, match="return code 1"):
        CLIRunner(argv=FAIL).run("x")


def test_a_runner_that_is_not_installed_says_so(tmp_path):
    """The likeliest failure here, and it used to be a raw traceback."""
    with pytest.raises(RunnerError, match="not installed"):
        CLIRunner(argv=[str(tmp_path / "no-such-agent")]).run("x")


def test_cli_runner_times_out():
    slow = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(RunnerError, match="timed out"):
        CLIRunner(argv=slow, timeout=1).run("x")


def test_get_runner_unknown():
    with pytest.raises(RunnerError, match="claude"):
        get_runner("clippy")
