# Design Documents

These are the design artifacts that drive the rebuild of the weather station. They were produced through a design conversation and are now **read-only inputs** for the implementation phase.

For project orientation, technology stack, phased delivery plan, and behavioral guidance, see `/CLAUDE.md` at the repo root.

## Reading order

| # | File | What it is |
|---|---|---|
| 1 | [`01-findings.md`](01-findings.md) | Original code review of the existing codebase + **decisions log** |
| 2 | [`02-api-design.md`](02-api-design.md) | HTTP API contract — endpoints, response schemas, field provenance |
| 3 | [`03-schema.md`](03-schema.md) | SQLite schema for outdoor history |
| 4 | [`04-server-architecture.md`](04-server-architecture.md) | Process model — single FastAPI process with internal async tasks |
| 5 | [`05-clients-scope.md`](05-clients-scope.md) | Dashboard and widget scope — what's added, removed, kept |
| 6 | [`06-dashboard-mockup.html`](06-dashboard-mockup.html) | Visual target for the dashboard (open in a browser) |

## If you only read one section

The **Decisions log** in `01-findings.md`. It records *why* every major design choice was made — including the ones that aren't obvious from the conclusion alone. When in doubt about whether to change something, that log is where to look first.

## Status

All decisions in these documents are **settled**. If you believe a decision is wrong, surface it as a question before changing direction. The design phase is complete; these files are inputs, not work-in-progress.

## How these docs reference each other

- `02-api-design.md` is the contract every other doc orbits around.
- `03-schema.md` describes the storage layer that feeds the API.
- `04-server-architecture.md` describes the process that runs the API.
- `05-clients-scope.md` describes the consumers of the API.
- `06-dashboard-mockup.html` is the visual realization of `05-clients-scope.md`'s dashboard requirements.
- `01-findings.md` is the historical record — what was wrong with the original code, what got removed, what got decided, and why.

Each design doc has a "How this maps to findings" or equivalent section that traces specific design choices back to the issues they resolve.
