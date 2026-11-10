# Contributing

Thanks for helping improve CloneX. This guide covers the local setup and the conventions the codebase follows.

## Setup

Install [uv](https://docs.astral.sh/uv/), then, on macOS, Linux or Windows:

```sh
git clone https://github.com/kaanxsrd/CloneX && cd CloneX
uv sync
uv run clonex --demo
```

## How the code fits together

- **`core/plan.py` only reads.** Everything that can be checked happens there, before the destination is touched.
- **`core/executor.py` writes,** one request at a time, and reports every step as done or skipped so progress stays exact.
- **`core/models.py` must not import `discord`.** That import costs over half a second, and `--help` and `--demo` never need it.
- **Every word a user reads comes from `clonex/locales/en.json`** through `t("key")`. Tests fail on a missing or unused key.
- **The tests use the real discord.py-self models** with only `HTTPClient` replaced (`tests/fakes.py`), so they also fail if the library stops accepting what CloneX sends.

## Before you open a pull request

```sh
uv run python scripts/check.py
```

This must pass: Ruff, formatting, mypy and the tests. CI runs the same checks on macOS, Linux and Windows.

Keep tests offline, and never add tokens or real Discord data to fixtures. Live testing must use authorized, disposable servers and never a production server.

## Conventions

- **Commits** follow [Conventional Commits](https://www.conventionalcommits.org): `feat(plan): ...`, `fix(ui): ...`, `docs: ...`.
- **Safety:** preserve preview mode, the typed confirmation, ID-based mappings and immediate stopping for critical failures. An omission must state its consequences and, in copy mode, get a decision. Include a regression test when fixing copy logic or permissions.
- **Security:** never log tokens, raw API responses or submitted values.
- **Wording:** a number next to a noun needs a plural form that many languages cannot build from a template, so write `Roles: {count}` rather than `{count} roles`.
- **Changelog:** add user-facing changes under `[Unreleased]` in `CHANGELOG.md`. That section becomes the release notes.

## Translations

The translations in `clonex/locales/` started as machine translations, so corrections from native speakers are very welcome: edit the language's JSON file. To add a language, copy `en.json` to `<code>.json`, translate the values, and keep every `{placeholder}`. The tests check every file for missing keys and changed placeholders. See [docs/languages.md](docs/languages.md).

When you change or add English text, update the other files too, or leave them: a missing key falls back to English, but the test suite requires every shipped language to be complete.

## Releasing

One version number lives in `clonex/__init__.py`.

1. Describe the changes under `[Unreleased]` in `CHANGELOG.md` and commit.
2. Once CI passes, cut the release and push it:

   ```sh
   python scripts/release.py minor    # or patch, major, or an explicit X.Y.Z
   git push --follow-tags
   ```

The script updates the version, dates the changelog section, and creates the commit and tag. `.github/workflows/release.yml` then runs the tests, builds and smoke-tests all six platform targets, and publishes a GitHub Release with the archives, `checksums.txt` and the changelog notes. It refuses a tag that disagrees with the code or has no changelog entry.

Two optional repository secrets also update the package managers. Without them those steps are skipped:

| Secret               | Grants                           |
| -------------------- | -------------------------------- |
| `HOMEBREW_TAP_TOKEN` | Push access to `kaanxsrd/homebrew-tap` |
| `SCOOP_BUCKET_TOKEN` | Push access to `kaanxsrd/scoop-bucket` |
