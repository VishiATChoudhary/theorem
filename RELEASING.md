# Releasing

A release is a tag. `.github/workflows/release.yml` fires on `v*`, checks
the tag against `theorem.__version__`, runs the tests, builds, and
publishes.

## Cutting one

```bash
# 1. bump both, they must agree or the workflow fails on purpose
#    pyproject.toml  version = "0.4.0"
#    src/theorem/__init__.py  __version__ = "0.4.0"
# 2. write the entry in CHANGELOG.md
uv run pytest -q
uvx ruff@0.16.5 check src tests eval && uvx ruff@0.16.5 format --check src tests eval
git commit -am "release: 0.4.0"
git tag -a v0.4.0 -m "theorem v0.4.0"
git push origin main v0.4.0
gh release create v0.4.0 --notes-file <(sed -n '/## 0.4.0/,/## 0.3.0/p' CHANGELOG.md)
```

Verify the artifact rather than the source tree, because the two differ:

```bash
uv build --out-dir /tmp/dist
uv venv /tmp/check && uv pip install --python /tmp/check/bin/python /tmp/dist/theorem-*.whl
/tmp/check/bin/theorem --help
```

## Publishing to PyPI

Two routes. Both upload the same two files, a wheel and an sdist, built
by `uv build` into `dist/`. Check them before either:

```bash
uv build
uvx twine check dist/*        # catches a README that will not render
tar tzf dist/theorem-*.tar.gz # 36 files; no eval data, no docs, no db
```

### Route A: trusted publishing (recommended, already wired)

No token is stored anywhere. GitHub proves its identity to PyPI over
OIDC, which is why this is the route the workflow uses.

It is not configured yet, which is why the v0.3.0 release run ended in
`Missing credentials`. Nothing was published, and the tag is otherwise
sound. To turn it on:

1. On PyPI, **Your projects, Publishing, Add a new pending publisher**
   (https://pypi.org/manage/account/publishing/) with:
   - PyPI project name: `theorem`
   - Owner: `VishiATChoudhary`
   - Repository name: `theorem`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
2. On GitHub, an environment named `pypi` must exist so the OIDC claim
   matches step 1. **It already does**: GitHub creates one the first time
   a workflow declares it, and release.yml does, so it appeared when the
   v0.3.0 tag run fired. No secrets go in it. Confirm with:

   ```bash
   gh api repos/VishiATChoudhary/theorem/environments --jq '.environments[].name'
   ```

   The page is in repo Settings, left sidebar under Code and automation.
   Not account settings, and absent on a private repo without a paid plan.
3. Re-push the tag to rerun the workflow:
   ```bash
   git push origin :refs/tags/v0.3.0 && git push origin v0.3.0
   ```

Check the name is still free before step 1: PyPI returned 404 for
`theorem` as of 2026-08-31, but names get taken.

### Route B: one-off from your machine

For a first upload when you would rather not set up OIDC yet. The token
is a secret: paste it at the prompt or put it in the environment, never
in a file that gets committed.

```bash
# https://pypi.org/manage/account/token/  scope: "Entire account"
# (narrow it to the theorem project after the first upload)
export UV_PUBLISH_TOKEN='pypi-...'
uv build
uv publish
```

Rehearse against TestPyPI first if you want to see the page before it is
permanent. TestPyPI is a separate account with a separate token:

```bash
UV_PUBLISH_TOKEN='pypi-...' uv publish --publish-url https://test.pypi.org/legacy/
pip install -i https://test.pypi.org/simple/ theorem
```

**A version is permanent.** PyPI will not let you re-upload `0.3.0` even
after deleting it, so a mistake costs a version number. Hence the
`twine check` above.

Once it publishes, change the install instructions in `README.md`,
`docs/index.md`, `docs/tutorial.md` and `docs/using-theorem.md` back to
`pip install theorem`, and restore the PyPI badge in the README.

## Docs

`docs.yml` builds with `mkdocs --strict` and deploys to GitHub Pages on
every push to `main`: https://vishiatchoudhary.github.io/theorem/
