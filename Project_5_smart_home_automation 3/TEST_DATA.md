# Test Data Guide - HomePulse 2.0

The included `seed.sql` provides a small happy-path baseline. Teams should create additional controlled data rather than depending entirely on manual clicking.

## Useful data categories
- Boundary values immediately below, at, and above every documented numeric/time limit.
- Multiple users in each role, including two users with similar resources to test horizontal authorization.
- Records in every workflow state, including terminal and invalid-transition candidates.
- Duplicate/replayed request identifiers and concurrent requests against the same resource.
- Dates/times around midnight, month boundaries, daylight-saving changes, and configured windows where relevant.
- User-controlled text beginning with unusual characters and strings at maximum/over-maximum lengths.
- Integration outcomes representing success, explicit failure, timeout/indeterminate result, and retry.
- Inconsistent database fixtures created deliberately in an isolated test database to evaluate reconciliation/health checks.

## Database reset
Delete `app.db` and restart the application to recreate schema + seed data. For automated tests, prefer a temporary database or transaction rollback strategy so tests are repeatable and independent.

## Do not use real sensitive data
All testing should use synthetic identities, locations, payment tokens, clinical/intake text, and device/home data.
