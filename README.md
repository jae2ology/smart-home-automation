# HomePulse 2.0 - Student Project Package

## Purpose
This is an **existing medium-complexity system under test** for CSCI 4534 Software Testing and Quality Assurance. Your team is not being asked to design the product from scratch. You are expected to evaluate the supplied requirements and implementation independently, design a risk-based test strategy, build repeatable tests, report defects, and support a release recommendation with evidence.

The supplied SRS is authoritative input to your QA process, but it is not guaranteed to be complete, internally consistent, or unambiguous. Likewise, the application is not represented as defect-free.

## Technology
- Python 3.11+ recommended
- Flask 3.x
- SQLite
- Server-rendered HTML/Jinja plus JSON endpoints
- pytest starter suite

## Functional surface
- Multi-home authorization
- Devices/tokens/telemetry
- Commands/scenes
- Rules/conflicts/cooldowns
- Schedules/timezones
- Alerts/monitoring
- Webhooks/retention/reconciliation


Current source size is approximately **197 Python lines** plus templates and SQL, with **23 database tables**. This is intentionally larger than a basic CRUD exercise.

## Setup
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Then open `http://127.0.0.1:5000/`.

To reset the supplied sample database, stop the application, delete `app.db`, and restart. The schema and seed data will be recreated automatically.

## Demo accounts
- `owner@example.com / student (owner)`
- `member@example.com / student (member)`
- `installer@example.com / install (installer)`
- `monitor@example.com / monitor (monitoring operator)`
- `admin@example.com / admin (administrator)`


**Important:** Credentials are deliberately simple because this is a local instructional artifact. Treat credential storage/authentication as part of the system quality surface; do not assume the implementation satisfies the security requirements.

## Supplied artifacts
- `SRS.docx` - formatted Software Requirements Specification
- `SRS.md` - searchable/editable copy of the same requirements
- `ARCHITECTURE.md` - high-level component and data-flow description
- `TEST_DATA.md` - seeded records and useful test-data ideas
- `app.py`, domain/integration helpers, `schema.sql`, `seed.sql`
- `templates/` - browser UI
- `tests/` - intentionally small starter pytest suite

## Suggested QA workflow
1. Review the SRS before extensive exploratory execution. Record requirements problems separately from implementation defects.
2. Build a traceability matrix and risk model.
3. Establish a repeatable database-reset/test-data process.
4. Test domain rules below the UI where practical (domain functions, database/state, APIs).
5. Add API/system tests and targeted browser-level tests.
6. Exercise concurrency, replay/idempotency, authorization, and integration failure scenarios where relevant.
7. Perform at least one substantive nonfunctional assessment.
8. Retest fixes/changes and present a Go / Conditional Go / No-Go recommendation.

## Endpoint inventory
The application currently defines approximately **19 route handlers**. Inspect `app.py` for exact methods and authorization decorators; route discovery itself is part of understanding the test surface.

## Academic-use note
Use only the synthetic sample data in this package. Do not enter real payment data, health data, credentials, addresses, or other sensitive personal information.
