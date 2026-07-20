# Release checklist

Use this checklist for every Home Assistant add-on release.

- [ ] All intended changes are documented in `CHANGELOG.md`.
- [ ] Tests, linting, YAML validation, and the add-on image build pass in CI.
- [ ] The version is identical in `config.yaml`, `Dockerfile`, `run.sh`, and
  the README badge.
- [ ] Upgrade notes cover schema migrations, changed entity IDs, and changed
  interpretation behavior, when applicable.
- [ ] The add-on starts with a clean install and upgrades an existing `/data`
  directory without data loss.
- [ ] The ingress UI, Lovelace card, and Home Assistant entity updates are
  smoke-tested.
- [ ] Release notes distinguish estimates from confirmed observations and do
  not make medical or contraceptive claims.
