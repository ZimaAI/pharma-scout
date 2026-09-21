# PharmaScount domain

## PharmaScount domain application

`app/pharma/` owns public drug intelligence, trial/publication snapshots, evidence,
research, independent report review, subscriptions and durable delivery. The
outer `PharmaDispatcher` routes only `/api/pharma/*`; its own mandatory sessions,
CSRF and workspace memberships are independent of the general Gateway identity.
Do not exempt generic Gateway routes or give domain sessions general agent tools.

Domain data uses a separate PostgreSQL database and Alembic history
(`app/pharma/migrations`). `Repository` scopes every business query; composite
foreign keys and immutable triggers protect evidence/report history. API sync work
runs through AnyIO threads; worker transactions must not span HTTP/LLM/SMTP calls.
Lease writes require owner_token, unexpired lease and current run/job association.

`intelligence_event.category` stores stable internal grouping keys. The API's
`event_view` maps them to the public OpenAPI enum and translates legacy automatic
titles without rewriting rows. Multiple historical groups may share a public
category; preserve their IDs, unique grouping constraint and immutable revisions.
First observations, including PubMed records, remain baselines without fabricated
change revisions. See `tests/test_pharma_events.py` for API/schema regressions.

The only model loop is the existing `create_deerflow_agent` factory via
`runtime.py`, with an explicit domain-only middleware and tool list. Never enable
shell, sandbox, arbitrary URLs, dynamic MCP or publish/email tools in this path.
DEMO replay and LIVE model execution remain explicit, with no automatic fallback.
The current historical cutoff freezes at min(run creation, requested end); newly
fetched candidates require a later run and mapping review before evidence use.

`resources/openapi.yaml` mirrors the reference contract; exported routes use
`/api/pharma/v1` to avoid existing auth names. Update contract, generated types,
fixtures and `BACKEND_HANDOFF.md` when interfaces change. Test with root
`make pharma-test` (real PostgreSQL integration requires PHARMA_TEST_DATABASE_URL,
private local configuration is loaded by scripts/pharma.py); `make verify-docs`
checks reference contracts. Integration fixtures create random schemas only in
explicit *_test databases and never truncate production tables.

## Product context

The medical R&D intelligence application lives in `backend/app/pharma/` and the
frontend `/pharma` namespace. Its scope and acceptance contract are in
`docs/reference/pharma-intelligence/`; actual interfaces and backend validation are
summarized in `BACKEND_HANDOFF.md`. Read root `design.md` before modifying its UI.
Domain API, sessions and workspaces are isolated at `/api/pharma/v1`, while the
existing general assistant remains at `/workspace`. Domain worker and PostgreSQL
commands: `make migrate`, `make seed-demo`, `make pharma-worker`, `make pharma-test`,
`make test-e2e`, `make verify-docs`. Demo credentials are generated privately; never
publish them in frontend code or use replay to claim live model verification.

The public brand is PharmaScount. Existing database/service names and account
identifiers remain stable. `seed-demo` recognizes the old branded workspace name
and renames that workspace in place instead of creating a second one.
