# BBT Fertility Tracker Roadmap

This is the shared plan for improving the Home Assistant add-on. It should be
updated when we complete a milestone or deliberately change priorities.

## Product guardrails

- Keep reproductive-health data private, local, and under the user's control.
- Treat dates and phases as observations or estimates, never guarantees or
  medical advice. The add-on must not be represented as contraception or a
  diagnostic tool.
- Prefer clear explanations over opaque predictions: users should be able to
  see the readings and rule behind every fertility insight.
- Maintain an excellent daily workflow on a phone inside Home Assistant.
- Do not expand the data collected unless it provides clear user value.

## How we work

- Complete milestones in order unless a security, privacy, or data-loss issue
  requires an earlier fix.
- Each change includes automated tests appropriate to its risk and an update
  to the README or in-app help when it changes user-visible behavior.
- Keep add-on, Docker, startup-log, and documentation versions aligned.
- Use a small release after each completed milestone, with upgrade notes.

## Milestone 0 — Project baseline

**Goal:** establish a reliable development and release foundation.

- [x] Add a Python test runner and a small, representative test suite.
- [x] Run linting and tests in CI; validate the Docker/add-on build as well as
  YAML syntax.
- [x] Add a changelog and a release checklist.
- [x] Correct version drift (`config.yaml` is 1.0.4 while Docker and startup
  output still identify 1.0.0).
- [x] Document local development, test, and add-on upgrade steps.

**Complete when:** a pull request can automatically verify code, tests, YAML,
and the add-on image; a release has one consistent version everywhere.

## Milestone 1 — Trust, privacy, and data safety

**Goal:** make the privacy promise and stored data dependable.

- [ ] Serve Chart.js, its annotation plugin, and the Lovelace card locally.
  Remove jsDelivr/CDN runtime dependency and document any build-time download.
- [ ] Add database schema versioning and forward-only migrations.
- [ ] Validate dates, temperature ranges, units, enum fields, and API input on
  every write path.
- [ ] Enforce profile ownership on all cycle/chart/API reads and writes.
- [ ] Add a profile-scoped data export and documented backup/restore process.
- [ ] Add deliberate, clearly worded confirmation for destructive actions such
  as deleting a profile or starting/replacing a cycle.

**Complete when:** the add-on works without external browser asset requests;
invalid or cross-profile data cannot be written/read; users can back up and
recover their records.

## Milestone 2 — Correct and explainable cycle interpretation

**Goal:** ensure insights are reproducible and understandable.

- [ ] Choose and document the exact sympto-thermal rules the add-on supports,
  including missing readings, discarded readings, and irregular cycles.
- [ ] Build fixtures/tests for standard and conservative shifts, temperature
  gaps, the supported exception rule, mucus/OPK observations, and incomplete
  cycles.
- [ ] Show an interpretation explanation: coverline, contributing readings,
  thermal-shift dates, confidence, and fertile-window rule.
- [ ] Separate labels and entities for confirmed observations versus estimates.
- [ ] Fix temperature-unit conversion so switching °F/°C converts historical
  data and derived values rather than only changing the unit label.
- [ ] Add safe re-analysis after corrections, settings changes, and migrations.

**Complete when:** test cases reproduce expected results and every displayed
insight links to a concise explanation of its underlying data and rule.

## Milestone 3 — Home Assistant-native experience

**Goal:** make the tracker predictable inside Home Assistant.

- [ ] Define stable entity IDs, availability behavior, units, device classes,
  and entity attributes.
- [ ] Provide validated actions/services for logging a temperature, marking a
  period start, and requesting re-analysis.
- [ ] Clarify and improve sensor import: preserve source/time, prevent
  accidental duplicate imports, and state that a generic ambient sensor is not
  automatically a valid BBT reading.
- [ ] Make Lovelace card installation/version updates reliable and local.
- [ ] Publish integration examples for dashboards and automations.

**Complete when:** Home Assistant users can build dashboards and automations
without relying on undocumented state conventions or public CDN assets.

## Milestone 4 — Daily logging and chart usability

**Goal:** make the common daily workflow fast, clear, and accessible.

- [ ] Improve the mobile entry flow with sensible defaults and clear saved/
  missing status.
- [ ] Improve charts with actual dates, readable gaps, annotations, and
  accessible text alternatives.
- [ ] Add a clear edit/history path for prior entries and cycle corrections.
- [ ] Add concise in-app help for discarding readings and interpreting results.
- [ ] Review color contrast, keyboard operation, labels, and small-screen
  layouts.

**Complete when:** a user can log, correct, and understand a day's data on a
phone without needing documentation or a desktop chart.

## Milestone 5 — Insights and optional expansion

**Goal:** add value without compromising the focused tracker.

- [ ] Add cross-cycle trend/comparison views based on completed cycles.
- [ ] Add configurable reminders using Home Assistant automation patterns.
- [ ] Decide, with user value documented, whether to support additional markers
  or data import/export formats.
- [ ] Add an opt-in feedback/diagnostic workflow that never sends sensitive
  data by default.

**Complete when:** new features are optional, documented, tested, and do not
weaken privacy or the core daily workflow.

## Active milestone

**Milestone 0 — Project baseline**

### Next work items

1. Run the new test suite in a Python 3.11 environment and resolve any
   platform-specific failures.
2. Confirm the CI Docker image build succeeds on GitHub Actions.
3. Add test cases whenever a bug or interpretation rule is changed.
4. Start Milestone 1 with local-only browser assets and database migrations.

## Decision log

| Date | Decision | Rationale |
| --- | --- | --- |
| 2026-07-19 | Prioritize trust and reliability before feature expansion. | Fertility data is sensitive; correct, recoverable, explainable behavior is the foundation for every later feature. |
| 2026-07-19 | Keep the app local-first and remove runtime CDN dependencies. | This matches the product's privacy and availability goals. |
