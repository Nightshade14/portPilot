# Repository Guidelines

## Project Structure & Module Organization

PortPilot is a planned migration harness that preserves behavior while porting a Flask service to a TypeScript/Hono service. The project charter is the current source of truth: `docs/charters/PROJECT_CHARTER.md`.

As implementation begins, keep the controlled Flask fixture, generated Hono target, Python harness, compatibility tests, and UI clearly separated. Prefer purpose-specific top-level directories such as `src/`, `tests/`, `fixtures/`, and `docs/`. Do not commit generated targets, local databases, virtual environments, credentials, or test artifacts unless they are intentional fixtures.

## Build, Test, and Development Commands

No application tooling is committed yet. Add documented commands alongside the tooling they require rather than assuming a package manager or runner.

The expected development flow is:

- Run the Flask fixture locally.
- Run the generated Hono target locally.
- Execute compatibility tests that compare HTTP status codes and JSON bodies.
- Run the Python harness against MongoDB Atlas using explicit environment configuration.

When commands are introduced, document their purpose in `README.md` and keep automated checks reproducible from a clean checkout.

## Coding Style & Naming Conventions

Use Python for the Strands migration harness and TypeScript for generated Hono services. Follow each language’s standard formatter and linter once selected; do not mix formatting conventions within a file.

Use `snake_case` for Python modules, functions, and variables. Use `camelCase` for TypeScript variables and functions, `PascalCase` for TypeScript types and classes, and lowercase kebab-case for directories. Give persisted MongoDB collections and documents stable, descriptive names such as `migration_runs`, `policy_version`, and `contract_result`.

## Testing Guidelines

Compatibility tests are the primary quality gate. Cover source and target behavior for successful requests, coercion, defaults, validation failures, HTTP `422` responses, and nested error schemas. Name tests after observable behavior, for example `test_normalize_coerces_numeric_strings`.

Keep contract cases deterministic and versioned. A policy may be promoted only when it improves the full suite without regressing previously passing cases.

## Commit & Pull Request Guidelines

The repository has only an initial commit, so no established commit convention exists. Use concise imperative subjects, such as `Add contract test runner`. Keep commits focused.

Pull requests should explain the behavioral change, identify affected fixture and target paths, link the relevant issue or charter milestone, and include test output. For UI changes, include screenshots or a short recording. Never include Atlas credentials, OpenRouter keys, or production-like data.
