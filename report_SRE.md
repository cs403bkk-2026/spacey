# SRE report: purchase service

Revision checked: `58adb41` (branch `refactor/purchase`, equal to `origin/refactor/purchase`). Compared against `origin/main` (`b4fec38`). Date: 2026-10-05.

Scope: the purchase code (`purchase/`, `access.py`, the booking, payment, unlock, account and space routes in `app.py`) and what it needs to run and deploy: its tests, Dockerfile, deploy job, config, health check and logs. The rest of the app was not reviewed.

## 1. Summary

**Safe to deploy this update.** All 173 tests pass, the image builds and runs, and the journey check differs from `origin/main` only where the purchase changes intend it to. Two reliability gaps already exist on `origin/main` and should be fixed soon: the app does not reconnect after a database restart, and `SECRET_KEY` is not set in the deploy.

## 2. What changed

There are no new commits since the previous check. `git fetch` showed `HEAD`, `origin/refactor/purchase` and the previous check all at `58adb41`.

Cumulative purchase-related change against `origin/main` (11 commits, 7 files, 344 insertions and 64 deletions):

- `86d5bb2` (PR #217): `purchase.py` moved to the `purchase/` package. The Dockerfile `COPY` was updated to match.
- `da4b9ee`: space and booking SQL moved into `purchase/space.py` and `purchase/booking.py`.
- `9456241`: one member-name rule for form and JSON bookings.
- `8c19743`: new `GET /me/bookings`.
- `5192321`, `4d380d5`, `f32d0dd`, `ab7de01`, `4b78b55`, `5337e6c` (PR #222): email and password validation, `register_user`, `authenticate`, `find_user_email` and `seed_starter_space` moved into `purchase/`. 12 unit tests added.

Files that changed in scope: `Dockerfile`, `openapi.yaml`, `purchase/__init__.py`, `purchase/booking.py` (renamed from `purchase.py`), `purchase/member.py`, `purchase/space.py`, `tests/test_purchase.py`. `app.py` and `tests/test_app.py` also changed.

Not changed since `origin/main`: `.github/workflows/delivery.yml`, `deploy/startup-app.nomad.hcl`, `gunicorn.conf.py`, `compose.yaml` and `requirements.txt` (`git diff --stat origin/main..HEAD` on those paths is empty).

Changes outside purchase that affect it: none found.

## 3. Checks

| Check | Command or file | Result | Evidence |
|---|---|---|---|
| pytest on the branch | `DATABASE_URL=postgresql://spacey:spacey@localhost:5433/spacey_test pytest -q` | Pass | `173 passed in 9.73s` |
| pytest on the baseline | same command, `origin/main` in a worktree | Pass | `157 passed in 7.83s`. The 16 extra branch tests are the new purchase tests. |
| Purchase unit tests alone | `pytest tests/test_purchase.py -q` | Pass | `18 passed in 0.15s` |
| Journey check, before | `journey.py` (28 steps) against `origin/main` on gunicorn | 23 pass, 5 fail | The 5 failures are features the branch adds or fixes (see below). |
| Journey check, after | same script against the branch Docker image | 27 pass, 1 fail | The one failure is `member=0` returning 400, which is an intended change. |
| Dockerfile | `Dockerfile:11-14`, `docker build -t spacey-review:branch .` | Pass | The build log shows `COPY app.py access.py gunicorn.conf.py ./` and `COPY purchase/ purchase/`. All `COPY` sources exist. `ls /app` in the container shows `access.py app.py gunicorn.conf.py purchase requirements.txt static templates`. |
| Container start | `docker run` with `DATABASE_URL` pointing at Postgres | Pass | `/health` answered within 1 second of `docker run`. |
| `/health` | `curl localhost:8102/health`, `app.py:446-456` | Pass | `{"revision":"branch","status":"ok"}` with HTTP 200. `revision` comes from `APP_REVISION`, which `deploy/startup-app.nomad.hcl:57` sets. |
| `/health` with the DB down | `docker compose stop db`, then `curl` | Pass | HTTP 503, `{"error":"database unreachable","status":"error"}`, 0.006s. |
| Recovery after a DB restart | `docker compose start db`, `pg_isready` accepting, wait 15s | **Fail** | `/health` stays 503 and `/spaces` stays 500. The log shows `psycopg.OperationalError: the connection is closed`. The same happens on `origin/main`. See issue 1. |
| Startup with an unreachable DB | `docker run -e DATABASE_URL=postgresql://x:y@host.docker.internal:1/z` | **Risk** | The container never exits. The log showed 2,425 `Booting worker` lines in about 6 minutes. See issue 2. |
| Deploy job | `.github/workflows/delivery.yml:46-113` | Pass (read only) | `build` needs `test`, `deploy` needs `build`. `deploy` runs only on `push` with `DEPLOY_ENABLED == 'true'`, and has `concurrency` with `cancel-in-progress: false` at lines 67-69. The `freshness` step skips a superseded revision. The verify step polls `/health` for the sha, 36 times 5s, which is 180s and matches `healthy_deadline = "3m"`. The job itself was not run. |
| Config: `DATABASE_URL` | `app.py:19`, `deploy/startup-app.nomad.hcl:62` | Pass | The Nomad template supplies it from the Nomad variable. The code reads it. CI and `compose.yaml` use the same name. |
| Config: `SECRET_KEY` | `app.py:25`, `docker exec ... env`, `deploy/startup-app.nomad.hcl:61-64` | **Fail** | `SECRET_KEY` is not in the container environment and not in the Nomad template. The app falls back to the public default `dev-secret-key-not-for-production`. |
| Config: `APP_REVISION` | `deploy/startup-app.nomad.hcl:57`, `app.py:456` | Pass | Set by the deploy and read by `/health`. |
| Logs | `docker logs spacey-review`, `gunicorn.conf.py` | Pass | 0 lines match `traceback\|error` in the healthy run. 0 lines contain `code=`. Lines look like `"GET /health HTTP/1.1" 200 36 0ms "curl/8.7.1"`. The log format is unchanged and excludes the referer and query string. |
| Timeouts | `gunicorn.conf.py`, `app.py:37`, `deploy/startup-app.nomad.hcl:89-91` | **Risk** | `grep` for `connect_timeout\|statement_timeout\|lock_timeout\|timeout` in `app.py`, `access.py` and `purchase/` finds nothing. `gunicorn.conf.py` sets only logging, so the default is 1 sync worker and 30s. The Nomad health check has `timeout = "2s"`. |
| Rollback | `deploy/startup-app.nomad.hcl:29-39`, `app.py:77-166` | Pass | `auto_revert = true`, `healthy_deadline = "3m"`, `progress_deadline = "5m"`. The update adds no table, column or constraint. The only new startup write is the idempotent `seed_starter_space` at `app.py:335`. |
| Stale references | `git grep` for the moved names | Pass | No caller outside `purchase/` and `app.py`. `tests/test_purchase.py:6` imports from `purchase.member`. |
| API contract | `openapi.yaml:288-300`, `openapi.yaml:256-262` | Pass | `/me/bookings` is documented. The 400 `member must be a string` is documented for `POST /spaces/{id}/bookings`. |

### Journey check: differences between `origin/main` and the branch

1. Booking `" Journey "`: `origin/main` stores it untrimmed, the branch stores `"Journey"`. This is the intended fix (`9456241`).
2. `GET /me/bookings`: `origin/main` returns 404, the branch returns 200 when logged in and 401 when logged out. This accounts for three of the five failures on `origin/main` (the original step, the logged-out step and the re-login step).
3. A blank `member` becomes `"guest"` on the branch. On `origin/main` the JSON path did not trim.
4. `"member": 0` returns 201 on `origin/main` and 400 `member must be a string` on the branch. This is the one failing step on the branch, and it is a deliberate rule change.

The 11 steps that exercise the moved account code give the same result on both revisions: duplicate register 409, bad email 400, short password 400, logout, wrong password 401, unknown email 401 with the identical message, non-string login 401, and re-login with a padded mixed-case email 200.

## 4. Issues

Most serious first.

1. **The app never reconnects after the database restarts.** `app.db` is one autocommit connection opened at import (`app.py:331`). Once Postgres restarts or drops the connection, every route that touches the database fails until the process restarts. Observed: after the DB came back, `/health` stayed 503 and `/spaces` stayed 500 for more than 15 seconds with Postgres accepting connections. The Nomad service check only marks the service unhealthy. `deploy/startup-app.nomad.hcl` has no `check_restart`, so nothing restarts the task. A routine DB restart or failover would take the purchase service down until someone restarts it by hand. This already exists on `origin/main`, so it is not a regression. Fix: reconnect on `psycopg.OperationalError` (or use a connection pool with `check=ConnectionPool.check_connection`), and as a safety net add a `check_restart { limit = 3, grace = "30s" }` block inside the `check` block in `deploy/startup-app.nomad.hcl:88-92`.
2. **`SECRET_KEY` is not set in the deploy.** The Nomad template injects only `DATABASE_URL` (`deploy/startup-app.nomad.hcl:61-64`). Production signs login sessions with the public default (`app.py:25`), so anyone can forge a session cookie. `GET /me/bookings` and the `/bookings/mine` page trust that session. Already on `origin/main`. Fix: add `SECRET_KEY={{ .secret_key }}` to the template and set `secret_key` in the Nomad variable. Optionally make the app refuse to start when `APP_REVISION != "local"` and `SECRET_KEY` is unset.
3. **A startup failure never makes the container exit.** With an unreachable `DATABASE_URL`, `get_connection` raises `SystemExit` (`app.py:42`) in the gunicorn worker. The master respawns the worker forever (2,425 respawns in about 6 minutes) and the container stays "running". Nomad's `restart` block (`deploy/startup-app.nomad.hcl:35-40`) never fires. The deploy still fails safely, because `/health` never answers and `auto_revert` rolls back after `healthy_deadline`, but the loop burns CPU and floods the log. Already on `origin/main`. Fix: add `preload_app = True` to `gunicorn.conf.py` so an import failure stops the master and the container exits (untested here), or add a bounded retry in `get_connection`.
4. **No timeouts on the database path.** There is no `connect_timeout`, `statement_timeout` or gunicorn `timeout`/`workers` setting, and one shared connection serves every request. A slow query blocks `/health` behind it, and the check times out at 2s. Not changed by this update. Fix: `psycopg.connect(..., connect_timeout=5, options="-c statement_timeout=5000")` at `app.py:37`, and explicit `workers`, `threads` and `timeout` in `gunicorn.conf.py`.
5. **Behavior change on `POST /spaces/{id}/bookings`.** A non-string `member` such as `0`, `false` or `[]` now returns 400 (`purchase/booking.py:39-41`). Before, `0` and `false` became `"guest"`. The new 400 is documented in `openapi.yaml:256-262`. Confirm no client sends these. Rollback is code-only. Fix, if a client does: send a string, or coerce on the client.
6. **Unbounded booking lists.** `purchase/booking.py:102`, `:109` and `:119` return every row with no `LIMIT`. Cost grows with data. Not a problem at the current size. Fix when volume grows: add `limit` and `offset` parameters.

## 5. Not checked

- **The live Nomad deploy and the GitHub Actions run.** I read `delivery.yml` and the Nomad file but cannot run them from here. I did not verify the GitHub secrets (`NOMAD_ADDR`, `NOMAD_TOKEN`), the variables (`DEPLOY_ENABLED`, `APP_HOSTNAME`) or the Nomad variable `nomad/jobs/spacey` that holds `database_url`.
- **Production data and migrations.** I ran against fresh scratch databases (`spacey_test`, `spacey_main`, dropped afterward), not a copy of production. This update adds no schema change, but I did not run the startup DDL against production-shaped data.
- **Load and slow-query behavior.** No load test was run (`scripts/load_test.py` was not used), so I cannot say how the single connection behaves under concurrent requests.
- **The CI `test` job on GitHub.** I ran pytest locally against Postgres 16 on port 5433 and read the job definition (Postgres 16, Python 3.12, `pytest`). I did not see the job run.
- **The journey check is my own script.** The repo has no journey check. I wrote `journey.py` in the session scratchpad. It covers the purchase flow (register, login, book, pay, unlock, list, cancel, metrics) and the changed edge cases. It is not in the repo.
- **Anything outside purchase.** Reporting, the dashboard redirect, templates and the README were not reviewed.

Housekeeping: this check started Docker Desktop (it had quit) and left the `spacey-db-1` container running. No code was changed. `report_SRE.md` is the only file created.
