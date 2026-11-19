# Backend tests for the held-out gate

`test_gate.py` exercises the confirmatory judgment end to end with FastAPI's
TestClient. `conftest.py` points the app at a temporary SQLite database and an
in-memory fake Redis, so no Postgres/Redis services are needed.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
```

Covered: exact one-sided binomial p-values (5/5, 0/5, 3/5), explored keys
rejected as holdout and vice versa, deleting an explored row keeps its
provenance, legacy observations are backfilled, holdout readings never appear
in list/analysis/export payloads, concurrent lock keeps one threshold, late
registration after lock rejected, interrupted frozen gate resumes without a
second judgment, and viewer can read aggregates but not lock or register.
