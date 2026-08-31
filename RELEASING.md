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

## PyPI, one-time setup

The workflow uses [trusted publishing](https://docs.pypi.org/trusted-publishers/),
so no token is stored anywhere. It is not configured yet, which is why
the v0.3.0 release run ended in `Missing credentials`. Nothing was
published, and the tag is otherwise sound.

To turn it on:

1. On PyPI, **Your projects, Publishing, Add a new pending publisher**
   (https://pypi.org/manage/account/publishing/) with:
   - PyPI project name: `theorem`
   - Owner: `VishiATChoudhary`
   - Repository name: `theorem`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
2. On GitHub, **Settings, Environments, New environment** named `pypi`.
   No secrets go in it; it exists so the OIDC claim matches step 1.
3. Re-push the tag to rerun the workflow:
   ```bash
   git push origin :refs/tags/v0.3.0 && git push origin v0.3.0
   ```

Check the name is still free before step 1: PyPI returned 404 for
`theorem` as of this writing, but names get taken.

Once it publishes, change the install instructions in `README.md`,
`docs/index.md`, `docs/tutorial.md` and `docs/using-theorem.md` back to
`pip install theorem`, and restore the PyPI badge in the README.

## Docs

`docs.yml` builds with `mkdocs --strict` and deploys to GitHub Pages on
every push to `main`: https://vishiatchoudhary.github.io/theorem/
