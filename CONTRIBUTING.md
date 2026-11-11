# Contributing

## Development environment

Requires Python 3.14. From the project directory:

```sh
python -m pip install -r requirements-test.txt pre-commit
pre-commit install
```

Validate changes locally before opening a pull request:

```sh
python -m pytest
ruff check custom_components tests
```

The test suite runs the integration against an isolated Home Assistant config
directory with mocked Sonos HTTP. Networking is blocked inside pytest; no test
talks to Sonos.

## Pull requests

Open a pull request against `main`. Do not push directly to `main` except for
release tooling commits.

## Releasing a new version

Version numbers live in `custom_components/sonos_web_reboot/manifest.json`.

1. Bump the version, either by editing `manifest.json` in a pull request or by
   running the **Version bump** workflow (`workflow_dispatch`) and merging the
   pull request it opens.
2. After the bump lands on `main`, run the **Release** workflow
   (`workflow_dispatch`) with the `version` input set to the new version. The
   workflow verifies `manifest.json`, runs lint and tests, builds
   `sonos_web_reboot.zip`, creates the `vX.Y.Z` tag and GitHub release, and
   attaches the zip asset.
3. Pushing a `vX.Y.Z` tag by hand works too; the **Release** workflow triggers
   on pushed tags and does the same checks before publishing.

The zip asset name must stay `sonos_web_reboot.zip`: HACS matches it exactly
against `filename` in `hacs.json`. The zip must contain the integration files
at its root (`manifest.json` at the top level), because HACS extracts it
directly into `custom_components/sonos_web_reboot`.
