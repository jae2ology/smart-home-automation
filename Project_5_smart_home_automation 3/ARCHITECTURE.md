# Architecture Overview - HomePulse 2.0

## Runtime shape
The application is a deliberately compact monolith so a student team can understand it within a semester while still testing cross-layer behavior.

```text
Browser / API client
        |
        v
Flask routes + session authorization
        |
        +--> domain helper functions
        +--> simulated external integration adapters
        |
        v
SQLite transactional data model (23 tables)
```

## Layers
- **Presentation/API layer:** Flask routes in `app.py` and Jinja templates under `templates/`.
- **Authorization layer:** session-based decorators in `auth.py`, plus route-specific ownership/role decisions.
- **Domain layer:** selected calculations and state-transition logic in `domain.py` where present.
- **Persistence layer:** `db.py`, `schema.sql`, and SQLite records. Foreign keys are enabled for normal connections.
- **Integration boundaries:** local adapters in `integrations.py` where the domain calls an external-style service.

## Testing implications
The architecture permits tests at several levels: pure/domain unit tests, database-backed integration tests, Flask route/API tests, state-machine tests, and end-to-end workflow tests. Do not assume route decorators or helper functions are correct merely because they exist. Validate business ownership rules and invariant preservation from observable behavior and database evidence.

## Data/state concerns
The application contains mutable workflow records, history/ledger records, and derived state. High-value QA questions include whether transactions are atomic, state transitions are legal, retries are safe, authorization is consistent between browser and API paths, and derived totals/statuses can be independently reconciled.
