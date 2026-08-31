"""The distribution is `theoremql`; the module is `theorem`.

PyPI prohibits the name `theorem`, so the two differ. That split is easy
to get wrong in exactly one direction: an extras spec names the
*distribution*, so `pip install "theorem[pdf]"` resolves nothing. These
pin the split and every place a name is written down.
"""

import re
import tomllib
from pathlib import Path

import pytest

import theorem

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
DIST = PYPROJECT["project"]["name"]


def test_the_distribution_is_not_the_module():
    assert DIST == "theoremql"
    assert theorem.__name__ == "theorem"


def test_the_build_backend_is_told_the_module_name():
    """uv infers it from the project name, which would be wrong here."""
    assert PYPROJECT["tool"]["uv"]["build-backend"]["module-name"] == "theorem"


def test_the_version_agrees_with_the_package():
    """The release workflow fails on a mismatch; catch it before the tag."""
    assert PYPROJECT["project"]["version"] == theorem.__version__


@pytest.mark.parametrize("extra", sorted(PYPROJECT["project"]["optional-dependencies"]))
def test_an_extras_message_names_the_distribution(extra):
    """`pip install "theorem[pdf]"` installs nothing. Every message that
    tells a user to install an extra has to say `theoremql`."""
    from theorem.ingest import normalize

    said = normalize.__file__ and Path(normalize.__file__).read_text(encoding="utf-8")
    for match in re.findall(r"[\w.-]+\[" + re.escape(extra) + r"\]", said):
        assert match.startswith(DIST), f"{match!r} should name {DIST}"


@pytest.mark.parametrize(
    "doc", ["README.md", "docs/using-theorem.md", "skills/theorem/SKILL.md"]
)
def test_a_doc_never_tells_you_to_install_the_module_name(doc):
    """Only what a reader would copy.

    These pages name `theorem[pdf]` on purpose, to say it resolves
    nothing. What must never appear is that spelling behind a
    `pip install`, so the match is anchored to the command.
    """
    text = (ROOT / doc).read_text(encoding="utf-8")
    installs = re.findall(r"(?:pip install|uv add)\s+\"?([\w.-]+\[[\w,]+\])", text)
    assert installs, f"{doc} shows no extras install to check"
    for spec in installs:
        assert spec.startswith(DIST), f"{doc} says `pip install {spec}`, not {DIST}"
