# Startup log

Append an entry at the end of every working day. Do not rewrite earlier entries to make the story
cleaner. On 25 September, assemble and submit this accumulated record.

For each day record:

- who worked on what;
- decisions and their reasoning;
- roles or ownership that emerged;
- what was skipped and why;
- what broke; and
- what changed.

## Day 1

### Work and ownership
- All three of us worked together on planning, the first slice, and getting everyone's laptop set up.
- Agreed together on the thinnest end-to-end journey and the 3-task split.
- Flurina set up the repo locally and pushed the `/spaces` change in two separate commits.
- Annabel and Gregory each reviewed and approved a pull request, so everyone got hands-on with the GitHub/PR workflow before kickoff.

### Decisions and reasoning
- No database yet: an in-memory list is enough to prove the journey works end to end, without locking in a schema too early.
- Payment and lock integration will be mocked for now, so the full journey an ship before we have real provider/hardware access.

### What we skipped
- Real persistence, real payment, real lock integration - deferred until the mocked versions prove the flow.
- Verifying the merged commit at the permanent URL — no deploy access yet (see blocker below).

### What broke or blocked us
- We can't do the "check it's live" step, because nothing is live yet.

### What changed by the end of the day
- Added `GET /spaces` to `app.py`, returning one hardcoded space.
- Added a matching test in `tests/test_app.py`. All tests pass.
- Everyone has the repo cloned, set up, and has reviewed at least one PR.

## 2026-09-09 - Day 2

### Work and ownership
- Agreed the MVP is: a member can make a reservation.
- Decided to hold off on the map/search/filter ideas until reservation works.
- We all implemented and tested `POST /spaces/<id>/bookings` together.
- PR: https://github.com/cs403bkk-2026/startup-app/pull/3

### Decisions and reasoning
- Reservation before browsing features: the core flow (book a space) matters more right now than how members find a space.
- Payment stays mocked, same reasoning as Day 1 - prove the flow works before adding a real provider.
- Booking a space that doesn't exist returns 404, so the API fails clearly instead of silently.

### What we skipped
- Map view, search bar, filtering by type/size/amenities - parked as ideas for after the reservation flow is solid, not dropped.
- Real payment and real unlock still mocked

### Help and tools
- Used Claude to help design the booking endpoint and its tests. We ran the
  tests ourselves and manually verified the 404 case before merging.

### What broke or blocked us
- Nothing new; deployment blocker from Day 1 is still open.

### What changed by the end of the day
- Added `POST /spaces/<id>/bookings` to `app.py`.
- Added two tests: successful booking, and booking a non-existent space (404). All 4 tests pass.

### Next steps
- Action: build the mocked unlock endpoint. Owner: Gregory. Checkpoint:
  next sync.

## 2026-09-15 - Day 3

**People and contributions**
- Gregory and Flurina worked through setting up the database together on Flurina's laptop, following what we agreed on in the last meeting

**Progress and evidence**
- Postgres is now running via Docker Compose (`db` service), and the app
  connects to it through `DATABASE_URL`.
- All 9 tests pass locally against the real Postgres container.
- PR: https://github.com/cs403bkk-2026/startup-app/pull/5

**Decisions and reasons**
- Went with Postgres over SQLite because that's what we agreed on in the last 
meeting, even though SQLite was working and needed zero setup (worth the extra 
complexity since it's the real database we'll actually use later)
- Kept the database logic simple (plain SQL, no ORM) so it's still easy for 
the rest of the team to read when they join.

**Attempts and problems**
- Ran into a confusing "role does not exist" error that turned out to be a second, unrelated Postgres already running directly on Flurina's laptop,competing for the same port as the Docker one. Took a while to figure out since the error didn't point at that directly. Had to check what was actually listening on the port to catch it.
- Fixed it by moving the Docker database to a different port on the host machine.

**Shortcuts and unfinished work**
- Still mocking payment and unlock.
- Map/search/filter UI still not started.
- Deployment blocker from Day 1 still open.

**Help and tools**
- Used Claude to debug - mainly to help spot where the code and the error 
messages disagreed, and to explain why the Postgres port conflict was happening. We made the actual changes and ran everything ourselves before merging.

**Next steps**
- Annabel needs to make sure she has Docker installed before pulling this branch, since tests now need a running Postgres container.
- Action: build the mocked unlock endpoint. Owner: Gregory.
- Action: still need `DEPLOY_ENABLED` - help needed, blocked on repo admin.

## 2026-09-16 - Day 4
#### Part 1: Prevent double-booking (issue #7)

**People and contributions**
- Roles split for the first time: Annabel picked issue, Flurina implemented.
- Picked issue #7 (prevent double-booking) as the first issue to close.

**Progress and evidence**
- `POST /spaces/<id>/bookings` now rejects a second booking on and already-booked space with `409 Conflict`.
- Verified with `pytest -q` (10 passed), including a new test for the double-booking case.
- PR: https://github.com/cs403bkk-2026/spacey/pull/12
- Also noticed Maksym updated the deployment workflow and Nomad job to actually run Spacey on the class infrastructure once DEPLOY_ENABLED is
turned on - no action needed from us yet, just confirmed our app code
didn't need to change for it.

**Decisions and reasons**
- Picked issue #7 first since it's a real bug that already existed (we checked - a space genuinely could be double-booked before this fix), and it needed no schema changes, unlike the time-range issue.
- Used 409 Conflict as the status code, since it's the standard HTTP code for "this conflicts with existing state" rather than a plain 400.

**Attempts and problems**
- None for this issue - straightforward once we found where the check needed to go.

**Shortcuts and unfinished work**
- This only blocks a second booking outright, it doesn't yet know about time ranges (that's issue #8, separate).
- Remaining open issues: #8 (time ranges), #9 (cancel a booking), #10 (list bookings for a space), (more are coming).

**Help and tools**
- Used Claude to help design and implement the fix. We reviewed the code, ran the tests ourselves, and manually confirmed the 409 case before merging.

**Next steps**
- Pick up issue #9 or #10 next (both simple, no schema changes needed).
- Action: still need `DEPLOY_ENABLED` turned on now that the deployment workflow is ready on the prof's side - help needed.

#### Part 2: Mocked unlock endpoint (issue #15)

**People and contributions**
- Same day, same roles: Annabel picked issue #15 next, Flurina implemented.

**Progress and evidence**
- `POST /bookings/<id>/unlock` now returns a mocked access code for a paid booking, 404 for an unknown booking (closes #15).
- Verified with `pytest -q` (12 passed).
- PR: https://github.com/cs403bkk-2026/spacey/pull/20

**Decisions and reasons**
- Picked #15 next since it completes the original core journey from issue #1 (find, book, pay, unlock) - the last mocked step still missing.
- Kept the unlock endpoint's "paid" check even though payment is currently always mocked true, so the endpoint stays honest about what it actually verifies.

**Attempts and problems**
- None - matched the pattern of the existing endpoints closely.

**Shortcuts and unfinished work**
- Access code is just a random string, no real lock hardware/API involved.
- Remaining open issues: #8 (time ranges), #9 (cancel a booking), #10(list bookings for a space), and several more added to the backlog today.

**Help and tools**
- Used Claude to help design and implement the endpoint. We reviewed the
code, ran the tests ourselves, and manually confirmed the unlock response before merging.

**Next steps**
- Annabel to pick the next issue from the backlog.

#### Part 3: Basic business metrics (issue #21)

**People and contributions**
- Annabel as business owner prioritized #21 next, since the metrics dashboard is a required deliverable, not just backlog cleanup. Flurina implemented it.

**Progress and evidence**
- `GET /metrics` now returns total spaces, total bookings, and distinct
  members, all counted live from the database.
- Verified with `pytest -q` (13 passed).
- PR: [paste feature/business-metrics PR link here]

**Decisions and reasons**
- Picked this over smaller CRUD issues because it's explicitly required
  for the 25 Sept deliverable (business-metrics dashboard fed by real
  data), and there's now real data worth reporting on.
- Left "revenue" out on purpose - there's no price field on bookings yet,
  so a revenue number would have to be invented. Needs a pricing decision
  first, which is a business call, not a code one.

**Attempts and problems**
- None - straightforward counts against existing tables.

**Shortcuts and unfinished work**
- No revenue metric yet (see above).
- No actual dashboard UI - this is just the data endpoint the dashboard
  will read from later.
- Remaining open issues: several from today's backlog (error response
  consistency, health check DB connectivity, etc.).

**Help and tools**
- Used Claude to help design and implement the endpoint. We reviewed the
  code, ran the tests ourselves, and manually confirmed the counts before
  merging.

**Next steps**
- Annabel to decide on a pricing model so a real revenue metric can be
  added.
- Annabel to pick the next issue from the backlog.

## 2026-09-17 - Day 5

#### Part 1: Health check confirms DB connectivity (issue #24)

**People and contributions**
- Annabel as business owner picked #24 next. Flurina implemented it.

**Progress and evidence**
- `GET /health` now runs a real database check (`SELECT 1`) and returns
503 if the database is unreachable, instead of only checking that Flask itself is up.
- Verified with `pytest -q` (14 passed), including a new test that closes the database connection and confirms `/health` reports the failure correctly.
- PR: https://github.com/cs403bkk-2026/spacey/pull/28

**Decisions and reasons**
- Picked this issue now specifically because the prof's recent deployment changes verify a deploy by polling `/health` - a health check that doesn't actually check the database would be misleading exactly when it matters most.
- Used 503 Service Unavailable, the standard status for "this service is temporarily unable to handle requests," rather than a generic 500.

**Attempts and problems**
- None - small, focused change.

**Shortcuts and unfinished work**
- Remaining open issues: consistent error shapes, list all bookings (not just per space), require a member name, capacity validation, input validation, update/delete a space, time ranges, cancel a booking, GET /spaces/<id>.

**Help and tools**
- Used Claude to help design and implement the check. We reviewed the code, ran the tests ourselves, and manually confirmed both the healthy and unreachable cases before merging.

**Next steps**
- Annabel to pick the next issue from the backlog.
- Action: still need `DEPLOY_ENABLED` turned on - help needed.

#### Part 2: Cancel a booking (issue #9)

**People and contributions**
- Gregory picked up #9 and implemented it. Annabel and Flurina both reviewed and approved the PR, Flurina merged it.

**Progress and evidence**
- `DELETE /bookings/<id>` now cancels a booking and returns the booking that was removed, or 404 if the booking doesn't exist (closes #9).
- Added two tests: cancelling a booking makes the space show as available again (and the booking can't be found anymore), and cancelling an unknown booking returns 404.
- Verified with `pytest -q` (16 passed, after merging in the health check changes from main).
- PR: https://github.com/cs403bkk-2026/spacey/pull/30

**Decisions and reasons**
- Went with actually deleting the row instead of marking it as cancelled, since that's what the issue asked for and it's the simplest version. Downside: a cancelled booking disappears from the `/metrics` counts completely.
- Kept the same `{"error": "booking not found"}` 404 as `GET /bookings/<id>` and the unlock endpoint, so all booking endpoints fail the same way.

**Attempts and problems**
- The code itself was quick, but running the tests locally on Gregory's laptop wasn't. First Docker wasn't running and `psycopg` wasn't installed in the venv, then the tests still couldn't connect to the database.
- Turned out `compose.yaml` puts Postgres on port 5433 (the fix from Day 3), but the app still defaults to 5432. Setting `DATABASE_URL` to port 5433 fixed it. The README doesn't mention this, so anyone following the README setup steps will hit the same problem.
- The branch fell behind main while we worked on it (the health check PR got merged in the meantime), so we merged main in and re-ran the tests before merging.

**Shortcuts and unfinished work**
- No check on who is cancelling - anyone can cancel any booking, since there's no login/auth yet.
- No refund logic, since payment is still mocked.
- Delete a space (#19) not started yet - Gregory will pick it up later.
- README still has the incomplete setup steps (no `docker compose up db -d`, no `DATABASE_URL`).

**Help and tools**
- Used Claude to help implement the endpoint and tests, and to debug why the tests couldn't reach the database locally (it spotted the 5432 vs 5433 port mismatch). We ran the tests ourselves and had two teammates review the PR before merging.

**Next steps**
- Action: fix the README setup steps so the new team can run the tests. Owner: Gregory.
- Action: implement delete a space (#19). Owner: Gregory.
- Action: still need `DEPLOY_ENABLED` turned on - help needed.

#### Part 3: Price and revenue tracking (issue #31)

**People and contributions**
- Flurina picked #31 next, since it unblocks the dashboard issue (#32), which needs real revenue data to show. Flurina implemented it.

**Progress and evidence**
- Spaces now have a price (`price_cents`, stored in cents to avoid floating-point rounding issues with money).
- `GET /metrics` now reports `revenue_cents`, summed from paid bookings.
- Verified with `pytest -q` (19 passed).
- PR: https://github.com/cs403bkk-2026/spacey/pull/35

**Decisions and reasons**
- Priced in cents as an integer, not a decimal/float, to avoid classic floating-point rounding bugs with money.
- Price defaults to 0 for spaces created without one, so existing behavior (and the seeded space) doesn't break.
- Picked this before the dashboard issue on purpose - building the dashboard first would have meant building it twice once revenue existed.

**Attempts and problems**
- None - the existing database already had the older schema without a price column, which was actually a good real test that our migration (`ADD COLUMN IF NOT EXISTS`) works on an existing database, not just a fresh one.

**Shortcuts and unfinished work**
- Revenue is a simple sum, not broken down by space or time period.
- Remaining open issues: dashboard page (#32, now unblocked), load test (#33), plus the earlier backlog.

**Help and tools**
- Used Claude to help design the schema change and revenue calculation. We reviewed the code, ran the tests ourselves, and manually confirmed the revenue number before merging.

**Next steps**
- Annabel to pick #32 (dashboard) next, now that real revenue data exists.
- Action: still need `DEPLOY_ENABLED` turned on - help needed.
#### Part 4: Time range for bookings (issue #8)

**People and contributions**
- Gregory implemented #8. PR is open and waiting for Annabels review.

**Progress and evidence**
- Bookings now need a `start_time` and `end_time` (date + time with timezone). A booking is only rejected with 409 if it overlaps an existing one, and `available` in `GET /spaces` now means "not booked right now" instead of "ever booked".
- Verified with `pytest -q` (20 passed - updated the existing booking tests to send times, plus 4 new ones), and CI is green.
- PR: https://github.com/cs403bkk-2026/spacey/pull/37

**Decisions and reasons**
- Times must include a timezone - we're in Bangkok but the server will probably run on UTC, so "09:00" alone would be ambiguous.
- Back-to-back bookings (10-11, then 11-12) are allowed, since they don't actually overlap.

**Attempts and problems**
- The issue text on GitHub for #8 was wrong (it had the double-booking description from #7 copied in), so we built what the title and our original backlog said. Issue text still needs fixing.

**Shortcuts and unfinished work**
- Two requests at the exact same moment could still both get through, since the overlap check and the insert are separate steps. Needs a database constraint before the load test.
- `/unlock` doesn't check if the booking is actually happening right now.

**Help and tools**
- Used Claude to help implement the overlap check and update the tests. We ran the tests ourselves and manually tried a Bangkok-time booking against an overlapping UTC one before opening the PR.

**Next steps**
- Action: review and merge PR #37. Owner: Annabel.
- Action: fix the issue #8 text on GitHub. Owner: Flurina.
- Action: open an issue for the simultaneous double-booking problem. Owner: Annabel.

#### Part 5: Load/capacity test (issue #33)

**People and contributions**
- Picked issue #33 specifically because it's a brand-new file (`scripts/load_test.py`, `LOAD_TEST.md`), so it couldn't conflict with the time-range work happening in `app.py` at the same time. Flurina implemented it.

**Progress and evidence**
- Added `scripts/load_test.py`, hitting GET /spaces at a configurable concurrency level and reporting latency/failure rate.
- Ran it for real at concurrency 5 and 50 (200 requests each) against a ocal gunicorn instance with 2 workers.
- Results documented in LOAD_TEST.md: 0 failures at both levels. Throughput held up (~1932 req/s at concurrency 5, ~2047 req/s at concurrency 50), but median latency rose about 9.6x over the same jump (2.2ms to 21.1ms).
- PR: https://github.com/cs403bkk-2026/spacey/pull/40

**Decisions and reasons**
- Concluded the first bottleneck is the small gunicorn worker pool (2 sync workers), not the database - throughput didn't collapse, but each request waited longer for a free worker, which shows up as rising latency rather than failures.
- Picked GET /spaces as the endpoint to hit since it's read-only and side-effect-free, so it's safe to hammer repeatedly.

**Attempts and problems**
- First attempt on a different machine had every request fail - the server process wasn't actually reachable yet when the script started. Fixed by adding a short wait after starting the server and confirming with a manual request first.

**Shortcuts and unfinished work**
- Run on a developer laptop, not the actual deployment target - absolute numbers will differ once DEPLOY_ENABLED is on and this runs on the real infrastructure.
- Remaining open issues: dashboard page (#32), delete a space (#19, in review), consistent error shapes, and the rest of the earlier backlog.

**Help and tools**
- Used Claude to help design and run the script. We reviewed the code, ran it ourselves against a real running instance, and the numbers in LOAD_TEST.md are the actual output, not estimated.

**Next steps**
- Once DEPLOY_ENABLED is on, re-run this against the real deployment for comparison.
- Gregory to pick the next issue from the backlog.

#### Part 6: Basic metrics dashboard (issue #32)

**People and contributions**
- Annabel as business owner picked #32 next, now that real revenue data
  exists (#31) to actually show. Flurina implemented it.

**Progress and evidence**
- Added `GET /dashboard`, a plain HTML page showing spaces, bookings,
members, and revenue - the first thing a person can actually look at,
not just JSON.
- Refactored the metrics query into a shared `compute_metrics` helper so
`/metrics` (JSON) and `/dashboard` (HTML) don't duplicate the SQL.
- Verified with `pytest -q` (24 passed) and manually by visiting
`/dashboard` in a browser.
- PR: https://github.com/cs403bkk-2026/spacey/pull/42

**Decisions and reasons**
- Kept it to plain HTML, no framework or styling - matches the brief's
"no premature abstraction" guidance, and it's easy for the team to read and extend later.
- Refactored the shared metrics logic out on purpose, rather than
copy-pasting the same four queries into a second route.

**Attempts and problems**
- None - small, focused change.

**Shortcuts and unfinished work**
- No styling, no charts, just numbers in a list.
- Remaining open issues: consistent error shapes, list all bookings (not per space), require a member name, capacity validation, input validation, update a space, GET /spaces/<id>, delete a space (#19, in review).

**Help and tools**
- Used Claude to help design and implement the endpoint and the refactor. We reviewed the code, ran the tests ourselves, and manually visited the dashboard before merging.

**Next steps**
- Annabel to pick the next issue from the backlog.

#### Part 7: Delete a space (issue #19)

**People and contributions**
- Annabel originally designed and implemented this in PR #39, including the endpoint and all three tests.
- Her branch was out of date and its CI was failing, so Flurina reimplemented the same logic fresh against current main, rather than untangling the stale branch.

**Progress and evidence**
- `DELETE /spaces/<id>` now deletes an unbooked space (204), rejects deleting a space that still has bookings (409), and returns 404 for an unknown space.
- Verified with `pytest -q` (27 passed).
- PR: https://github.com/cs403bkk-2026/spacey/pull/44
- Closed #39 in favor of this PR.

**Decisions and reasons**
- Kept Annabel's exact approach: reject deletion outright if any booking exists, rather than cascading the delete - safer, and consistent with how the app already treats bookings as something that should be explicitly cancelled, not silently destroyed.

**Attempts and problems**
- Found why #39's CI was failing: that branch predates the time-range work merging into main, so its booking-creation test call was missing the now-required start_time/end_time fields. Not a mistake in the delete logic itself - just a branch that fell behind main.

**Shortcuts and unfinished work**
- Remaining open issues: consistent error shapes, list all bookings (not per space), require a member name, capacity validation, input validation, update a space, GET /spaces/<id>.

**Help and tools**
- Used Claude to help identify why the original PR's CI was failing and to port the logic forward cleanly. We reviewed the code, ran the tests ourselves, and confirmed all three cases before merging.

**Next steps**
- Annabel to pick the next issue from the backlog.

## 2026-09-18 - Day 6

#### Part 1: Fix booking race condition (issue #50)

**People and contributions**
- Flurina picked up issue #50 (business owner call: a booking system that can double-book under load is a correctness bug in the core feature, not a nice-to-have, and it directly follows up on the load test work from #33).

**Progress and evidence**
- Added a Postgres exclusion constraint on `bookings` (`space_id` + `tstzrange(start_time, end_time)`) so the database itself rejects a second overlapping booking, even if two requests race past the existing application-level check. The insert is wrapped in a try/except so a constraint violation still returns the normal `409 space is already booked for that time` instead of a 500.
- New test creates two separate app instances (two real DB connections, like two real simultaneous requests would get), fires both bookings for the same slot at the same instant using a `threading.Barrier`, and asserts exactly one `201` and one `409` come back. Ran it 5x standalone - passed every time.
- `pytest -q`: 28 passed (27 existing + 1 new).
- PR: https://github.com/cs403bkk-2026/spacey/pull/51

**Decisions and reasons**
- Chose the DB-constraint fix over the other option in #50 (wrapping the check in a transaction with `SELECT ... FOR UPDATE`). Our app currently keeps one long-lived connection per app instance rather than a connection pool, which makes an app-level lock unreliable across requests; a constraint is enforced by Postgres per statement regardless of how the app manages connections, so it's the simpler and more "boring" fix given our no-ORM setup.
- Kept the original pre-insert overlap check in place as the fast, friendly path (it fires first in the non-racing case); the constraint is a backstop for when it's raced.

**Attempts and problems**
- First attempt at the constraint used `tsrange(start_time, end_time)`, which failed at startup with `UndefinedFunction: tsrange(timestamp with time zone, ...)` - our columns are `TIMESTAMPTZ`, so the range function needs to be `tstzrange`, not `tsrange`. Caught immediately by actually running the test suite rather than assuming the SQL was right.

**Shortcuts and unfinished work**
- Not exercised under real multi-process load (e.g. gunicorn with multiple workers) yet, only two app instances in a test - worth confirming again once we deploy with more than one worker.
- Remaining open issues: consistent error shapes, list all bookings (not per space), require a member name, capacity validation, input validation, update a space, GET /spaces/<id>, ownership checks on cancel/unlock, env var docs, README update, homepage space list.

**Help and tools**
- For this issue I used Claude Code for the first time, instead of the chat interface we'd used before. I still reviewed every line of the code, and independently re-ran the concurrency test 5 times to check it wasn't just getting lucky before trusting the result.

**Next steps**
- Get a teammate to review and merge PR #51.
- Gregory or Annabel to pick the next issue from the backlog.

#### Part 2: Add GET /spaces/<id> (issue #13)

**People and contributions**
- Flurina picked up issue #13 and implemented it.

**Progress and evidence**
- `GET /spaces/<id>` now returns a single space's data (same shape as one entry in `GET /spaces`, including `available`), and 404 for an unknown id.
- Verified with `pytest -q` (29 passed: 27 existing + 2 new).
- PR: https://github.com/cs403bkk-2026/spacey/pull/53

**Decisions and reasons**
- Picked #13 next since it's small, needs no schema changes, and doesn't touch `create_booking` - no overlap with the still-unmerged race-condition fix (#50, PR #51).

**Attempts and problems**
- None - small change, mirrors the existing `GET /spaces` query.

**Shortcuts and unfinished work**
- Remaining open issues: consistent error shapes, list all bookings (not per space), require a member name, capacity validation, reject invalid space input, update a space, ownership checks on cancel/unlock, env var docs, README update, homepage space list.

**Help and tools**
- Used Claude Code again. This time I had it propose the change first without applying anything, reviewed the diff, applied it myself, and ran the tests myself before pushing.

**Next steps**
- Get teammates to review and merge PRs #51, #52, #53.
- Gregory or Annabel to pick the next issue from the backlog.

#### Part 3: List all bookings for a space (issue #10)

**People and contributions**
- Gregory and Annabel picked up #10 and implemented it. Flurina reviewed, approved and merged the PR.

**Progress and evidence**
- `GET /spaces/<id>/bookings` now returns all bookings for a space, earliest first, and 404 for an unknown space. A space with no bookings returns an empty list.
- Verified with `pytest -q tests` (33 passed, 30 existing + 3 new), ran it 6 times in a row. CI green.
- PR: https://github.com/cs403bkk-2026/spacey/pull/54

**Decisions and reasons**
- Returned `{"bookings": [...]}`, same shape as `GET /spaces` returning `{"spaces": [...]}`, and reused the same booking format as `GET /bookings/<id>` so everything looks the same.

**Attempts and problems**
- Plain `pytest` broke before running any test: it also picks up `scripts/load_test.py` (the name matches pytest's `*_test.py` pattern), which needs `requests`, and that wasn't installed in Gregory's venv yet. Ran `pytest tests` instead.
- The concurrency test from Part 1 failed once in a full run. Checked it on main without our change - it failed there too (1 of 6 runs), so it's flaky and not caused by this PR. Couldn't reproduce it again to see the actual error.

**Shortcuts and unfinished work**
- No filtering (e.g. only upcoming bookings) - just returns everything for that space.
- Flaky concurrency test not fixed yet.

**Help and tools**
- Used Claude Code to implement the endpoint and tests, and to check whether the failing concurrency test was our fault by running the suite with and without our change. Gregory reviewed the diff and a teammate reviewed the PR before merging.

**Next steps**
- Action: add `testpaths = tests` to `pytest.ini` so pytest stops picking up the load test script. Owner: Gregory and Annabel.
- Action: open an issue for the flaky concurrency test. Owner: Flurina (wrote the test in #51).

#### Part 4: List all bookings across every space (issue #23)

**People and contributions**
- Flurina picked up issue #23 and implemented it.

**Progress and evidence**
- `GET /bookings` now returns all bookings across every space, earliest first.
- Verified with `pytest -q` (35 passed: 33 existing + 2 new).
- PR: https://github.com/cs403bkk-2026/spacey/pull/59

**Decisions and reasons**
- Picked #23 next since it complements #10 (per-space listing, just merged) and is explicitly wanted by the dashboard/load-test work - small, no schema changes.
- Reused the same `{"bookings": [...]}` shape and formatting as the per-space endpoint, so the two stay consistent.

**Attempts and problems**
- None - small addition, same query pattern as the per-space listing endpoint from Part 3.

**Shortcuts and unfinished work**
- No filtering (e.g. by space, by date range) - just returns everything.
- Still open: consistent error shapes, require a member name, capacity validation, reject invalid space input, update a space, ownership checks, env var docs, README update, homepage space list, availability for a specific time slot (#56), dead code in /metrics (#57), and the flaky concurrency test / missing `testpaths` config flagged in Part 3.

**Help and tools**
- Used Claude Code again: it proposed the change first, I reviewed and applied it myself, and ran the tests myself before pushing.

**Next steps**
- Get a teammate to review and merge PR #59.
- Someone to pick up the flaky concurrency test and `testpaths` fix flagged in Part 3.

#### Part 5: Remove dead code in /metrics (issue #57)

**People and contributions**
- Flurina picked up issue #57 (quick cleanup).

**Progress and evidence**
- Removed the ~20 lines of commented-out pre-refactor code in `metrics()`. Behavior unchanged.
- Verified with `pytest -q` (38 passed, unchanged).
- PR: https://github.com/cs403bkk-2026/spacey/pull/62

**Decisions and reasons**
- No design decisions - straight deletion, git history keeps the old code if ever needed.

**Attempts and problems**
- None.

**Shortcuts and unfinished work**
- None for this one.

**Help and tools**
- None.

**Next steps**
- Gregory or Annabel to pick the next issue from the backlog.
#### Part 6: Validate booking doesn't exceed space capacity (issue #16)

**People and contributions**
- Gregory and Annabel implemented #16. Annabel reviewed and approved the PR first, and she also merged Flurina's #59 around the same time. Flurina then approved and merged ours.

**Progress and evidence**
- Bookings now take an optional `party_size` (default 1). If it's bigger than the space's capacity, the booking is rejected with 400 and a message saying why, e.g. `party_size 2 exceeds this space's capacity of 1`.
- 3 new tests (too many people, exactly at capacity, invalid values like `0` or `"two"`). 36 passed locally, 38 on main after #59 came in, CI green.
- PR: https://github.com/cs403bkk-2026/spacey/pull/60

**Decisions and reasons**
- Made `party_size` optional so the load test script and existing tests didn't need to change.
- Used 400 instead of 409 - the request itself is wrong, it's not a clash with another booking.

**Attempts and problems**
- Annabel's approval got dismissed automatically: #59 merged first, we merged main into our branch, and GitHub treats a new commit as needing a fresh review. Flurina re-approved it after the update.

**Shortcuts and unfinished work**
- `party_size` is only checked, not saved, so it doesn't show up in bookings or metrics yet.

**Help and tools**
- Used Claude Code to implement the check and tests. Gregory ran the tests himself and reviewed the diff, and Annabel and Flurina reviewed the PR.

**Next steps**
- Action: decide if we want to store `party_size` (e.g. for a "people booked" metric). Owner: Annabel.
- Action: `testpaths` fix and flaky concurrency test are still open from Part 3.

#### Part 7: Reject invalid space creation input (issue #17)

**People and contributions**
- Gregory and Annabel implemented #17. Flurina reviewed, approved and merged it.

**Progress and evidence**
- `POST /spaces` now rejects an empty or whitespace-only name, and a capacity that isn't a whole number of at least 1 (0, -5, `"6"`, 2.5, `true`), both with 400 and a clear message. Spaces around the name get trimmed before saving.
- 3 new tests, 41 passed (ran it 5 times), CI green.
- PR: https://github.com/cs403bkk-2026/spacey/pull/67

**Decisions and reasons**
- Kept the old "name and capacity are required" message for missing fields, so the existing test and anyone relying on it still work - new messages only for values that are there but make no sense.
- Used the same wording as the `party_size` check from Part 5 ("whole number of at least 1"), so the errors read the same across the API.

**Attempts and problems**
- None in the code. Only hiccup: the log branch was created before the PR got merged, so it was one merge behind main - pulled main before writing this.

**Shortcuts and unfinished work**
- `price_cents: true` still gets accepted (saved as 1) - same bool-counts-as-a-number issue, just in a different field. Not fixed here to keep the PR on #17.
- Two entries in this log are both called "Part 5" (dead /metrics code and capacity validation) - left as is, since we don't rewrite earlier entries.

**Help and tools**
- Used Claude Code for the validation and tests. Gregory reviewed the diff and ran the tests, Flurina reviewed the PR.

**Next steps**
- Action: small follow-up issue for the `price_cents: true` case. Owner: whoever is business owner next.

#### Part 8: Update a space (issue #18)

**People and contributions**
- Gregory and Annabel implemented #18. Annabel reviewed and approved the PR. Still needs main merged in before it can be merged (the homepage PR #69 landed in between).

**Progress and evidence**
- New `PATCH /spaces/<id>`: updates `name` and/or `capacity`, only what's sent. 404 for an unknown space, 400 for empty/invalid values with the same messages as creating a space.
- 5 new tests, including one that checks a space's bookings survive the update (the whole reason for the issue). 46 passed locally, CI green.
- PR: https://github.com/cs403bkk-2026/spacey/pull/70

**Decisions and reasons**
- Moved the name/capacity checks from #17 into two small functions (`is_valid_name`, `is_valid_capacity`) so creating and updating a space follow the exact same rules instead of two copies drifting apart.

**Attempts and problems**
- While running the tests 20+ times, the flaky concurrency test from #51 failed again, and this time we caught the actual error: Postgres sometimes detects a **deadlock** between the two simultaneous bookings. Postgres cancels one of them (fine), but we only catch `ExclusionViolation`, so that member gets a 500 instead of a 409. The failing runs were always ~1 second slower, which matches Postgres's 1-second deadlock check - that's what gave it away. Not caused by this PR (fails on main too).

**Shortcuts and unfinished work**
- `price_cents` can't be updated yet (not part of #18).
- Lowering capacity isn't checked against existing bookings, since `party_size` isn't stored.
- Deadlock fix not done yet - separate issue.

**Help and tools**
- Used Claude Code to write the endpoint and tests, and to dig into the flaky test (it re-ran the suite until it failed and pulled the deadlock out of the Postgres logs). Gregory reviewed the diff, Annabel reviewed the PR.

**Next steps**
- Action: merge main into `update_space`, re-run tests, merge PR #70. Owner: Annabel and Gregory.
- Action: open an issue + fix for the deadlock (also catch `DeadlockDetected`, return 409). Owner: Flurina and Gregory.

#### Part 9: Replace the homepage with a real space list (issue #49)

**People and contributions**
- Annabel the business owner picked issue #49 and Flurina implemented it.

**Progress and evidence**
- `GET /` now renders a plain HTML list of spaces (name, capacity, price, available/booked), reading the same data `GET /spaces` already returns - no JS framework, no styling, matching how `/dashboard` was done.
- Verified with `pytest -q` (43 passed: 41 existing + 2 new).
- PR: https://github.com/cs403bkk-2026/spacey/pull/69

**Decisions and reasons**
- Picked #49 next since #65 (booking form) and #66 (confirmation page) both explicitly depend on a real homepage existing first.
- Escaped the space `name` with `markupsafe.escape()` before rendering it into the page, since it's user input (from `POST /spaces`) - without that, a space named e.g. `<script>...</script>` would be a stored XSS hole. Added a test that specifically checks a script-tag name gets escaped, not executed.

**Attempts and problems**
- None - straightforward once the escaping question was settled.

**Shortcuts and unfinished work**
- No styling, no booking form yet - just a list (#65, #66 next).
- Remaining open issues: booking form (#65), confirmation/unlock page (#66), availability for a specific time slot (#56), ownership checks (#48), env var docs (#47), README update (#46), consistent error shapes (#25), require a member name (#22).

**Help and tools**
- Used Claude Code again: it proposed the change (including flagging the XSS risk itself), I reviewed and applied it, and ran the tests myself before pushing.

**Next steps**
- Whoever's free next: pick up #65 (booking form), now that #49 unblocks it.

## 2026-09-20 - Day 7

#### Part 1: Bookings start unpaid, mocked pay endpoint (issue #74)

**People and contributions**
- We all implemented #74. Flurina reviewed, approved and merged it.

**Progress and evidence**
- Bookings are now created with `paid: false`, and a new `POST /bookings/<id>/pay` flips them to paid (404 if the booking doesn't exist). Unlocking before paying now actually fails with the existing 402 "booking is not paid".
- 4 new tests, 5 existing ones updated to do the pay step. 52 passed (5 runs), CI green.
- PR: https://github.com/cs403bkk-2026/spacey/pull/76

**Decisions and reasons**
- Came out of the meeting with Maksym: payment should be a visible step in the flow, not something that silently happens on booking, even while the money movement stays fake.
- Paying twice just returns the paid booking instead of erroring, so a double-click or a retry can't break the flow.

**Attempts and problems**
- Changing the default broke a test we didn't expect: the dashboard test checked for `$15.00` revenue, which is now $0.00 until someone pays. Fixed by paying in the test first. Same for the metrics revenue test.

**Shortcuts and unfinished work**
- Payment is still completely fake - no provider, no amount checked, no failure case.
- No UI for it yet: #75 (Pay button) is the follow-up.
- Revenue on the dashboard now only counts bookings that went through `/pay`, so the number will look lower than before - that's intentional, it's just honest now.

**Help and tools**
- Used Claude Code for the change and tests. Gregory ran the tests and reviewed the diff, Flurina reviewed the PR.

**Next steps**
- Action: #75 (Pay button in the UI), now that the endpoint exists. Owner: Annabel and Gregory

#### Part 2: Navigation links (issue #73)

**People and contributions**
- Picked #73 specifically because it's isolated from Gregory's in-progress work on #74 (unpaid bookings/pay endpoint) - zero overlap zero conflict risk. Flurina implemented it.

**Progress and evidence**
- Added a link from / to /dashboard, and back.
- Verified with pytest, including two new tests confirming each link renders.
- PR: https://github.com/cs403bkk-2026/spacey/pull/79

**Decisions and reasons**
- Kept it to a plain text link, no nav bar - matches Maksym's guidance to keep the UI basic and functional for now, not polished.

**Attempts and problems**
- None - small, isolated change.

**Shortcuts and unfinished work**
- Still no real navigation (header/menu) - just two links. Fine for now given the "basic UI" guidance.

**Help and tools**
- Used Claude to help implement and test the change. Ran the tests ourselves before merging.

**Next steps**
- Once #74 merges, pick up #75 (Pay button) next.

## 2026-09-21 - Day 8

#### Part 1: Split paid and unpaid bookings in /metrics (issue #85)

**People and contributions**
- Flurina picked #85 and implemented it.

**Progress and evidence**
- `/metrics` now also returns `paid_bookings` and `unpaid_bookings`; `bookings` stays as the total.
- `pytest -q tests`: 56 passed, 5 runs in a row (54 existing, 2 new, 1 updated for the new keys). The metrics tests fail on main and pass with the change.
- PR: https://github.com/cs403bkk-2026/spacey/pull/88

**Decisions and reasons**
- Picked #85 because since #74 the single bookings number is ambiguous, and the metrics dashboard is due Tuesday. It also touches only compute_metrics, so no overlap with Annabel's booking form work (#65, branch `add_booking_form` is still empty).
- Left out #78 for now: it says PATCH /spaces can change a price, but PATCH only updates name and capacity, so that bug can't be triggered through the API yet. Needs a decision first: should PATCH support price?
- #84 (paying twice) looks already true by design: revenue counts the `paid` flag, so paying twice can't count twice. Only a test is missing.

**Attempts and problems**
- None for the code itself.

**Shortcuts and unfinished work**
- `/dashboard` still shows only the total, not the split.
- Flaky concurrency test from Part 3 (Day 6) not fixed yet; it didn't fail in 5 runs today.

**Help and tools**
- Used Claude Code to implement it. I reviewed everything and ran the tests before pushing.

**Next steps**
- Action: #75 (Pay button in the UI), now that the endpoint exists. Owner: Annabel and Gregory

                           
#### Part 2: Booking form on the space list (issue #65)

**People and contributions**
- Annabel and Gregory implemented #65. Annabel reviewed, approved and merged it.

**Progress and evidence**
- Every available space on the homepage now has a small form (name + start/end time + Book button). Booking redirects back to the list, which shows "Booked! Booking #N - not paid yet" and flips the space to booked. Errors (slot taken, missing times) come back as a message on the page.
- New `POST /spaces/<id>/book` for the form; the JSON API is unchanged. The booking rules now live in one shared `book_space()` used by both, instead of two copies.
- 6 new tests, 59 passed locally (5 runs), CI green. Also clicked it through a running app over real HTTP to check the redirect, the message, and that the space flips to booked.
- PR: https://github.com/cs403bkk-2026/spacey/pull/89

**Decisions and reasons**
- The browser's date/time field sends no timezone, so form times are read as Bangkok time.
- The page says so under the heading. The JSON API still demands an explicit timezone, so scripts can't get it wrong by accident.
- The form posts to its own URL and redirects, rather than making the JSON endpoint return HTML sometimes - a browser form can't display JSON, and mixing the two would make both harder to follow for the handover team.

**Attempts and problems**
- First test run failed in a confusing way: a booking "happening now" showed as available. The test helper built the time from UTC wall-clock, but the app reads form times as Bangkok, so the booking landed 7 hours in the past. Fixed the helper to use Bangkok wall-clock.


**Shortcuts and unfinished work**
- The form always books for 1 person, no party size field yet (the API still enforces capacity).
- No confirmation page (#66) and no Pay button (#75), so a booking made in the browser stays unpaid and can't be unlocked without curl.
- Small API behaviour change: unknown space + missing times now returns 400 instead of 404, since times are parsed before the space lookup.

**Help and tools**
- Used Claude Code for the form, the shared booking function and the tests, and to run the app and check it end to end over HTTP. Gregory and Annabel reviewed the diff and ran the tests, Annabel reviewed the PR.

**Next steps**
- Action: #75 (Pay button) and #66 (confirmation + unlock code) - together they finish the clickable find → book → pay → unlock demo
- Action: #46 (README) before the handover - the current setup steps still don't mention `docker compose up db -d` or the 5433 port.
- Action: decide whether PATCH /spaces should support price_cents, so #78 can go ahead. Owner: Annabel (business owner).
- Action: #84 only needs a test that revenue goes up once. Owner: whoever is free.

#### Part 3: Availability for a requested time window (issue #56)

**People and contributions**
- Annabel picked #56 and told Flurina to implemented it.

**Progress and evidence**
- `GET /spaces` and `GET /spaces/<id>` accept optional `?start_time=&end_time=`. With them, `available` means free for that whole window (same overlap rule as booking creation, back-to-back is fine); without them it still means "right now".
- `pytest -q tests`: 66 passed, 5 runs in a row (61 existing, 5 new).
- PR: https://github.com/cs403bkk-2026/spacey/pull/92

**Decisions and reasons**
- Picked #56 because it answers the core question of the product ("is this free next Tuesday 2-4pm?") and only touches the spaces endpoints, so no overlap with Annabel's booking form work.
- Left out #66/#75 (confirmation page, Pay/Unlock buttons) on purpose: the Day 7 log names Annabel and Gregory as owners and we couldn't see whether they had started.
- Both params are required together, with a timezone; otherwise a 400 that says why. The response shape did not change.

**Attempts and problems**
- One of my new tests (the back-to-back boundary) also passed on the old code, so it proved nothing. Fixed it by booking the space right now, which makes the old code fail.
- A literal `+` in a query string becomes a space, so `+07:00` gives a 400. Use `Z` or `%2B`. The error message now suggests `Z`.

**Shortcuts and unfinished work**
- The homepage still shows availability for "right now" and the booking form doesn't use the window yet.
- No timezone default for the query params.

**Help and tools**
- Used Claude Code to implement app.py and test_app.py. I checked that the new tests fail with `app.py` reverted to main, re-ran the suite 5 times and reviewed the diff.

**Next steps**
- Action: tell Annabel and Gregory that #56 is done, and check who takes #66/#75 (confirmation page, Pay, Unlock). Owner: Flurina.
- Action: decide whether the homepage should show availability for the time slot a person types into the form. Owner: Annabel (business owner).

#### Part 4: Let the mocked payment fail (issues #83, #84)

**People and contributions**
- Annabel (business owner) picked #83 and assigned it to Flurina, who implemented it. #84 turned out to be covered by the same endpoint, so it was closed with it.

**Progress and evidence**
- `POST /bookings/<id>/pay` now takes an optional `{"force_failure": true}`. It returns 402 "payment failed" and the booking stays unpaid, so unlock returns 402 and no revenue is counted. Without the flag (or with `false`) nothing changes, and an already paid booking stays paid.
- #84: a new test pays the same booking twice and checks `revenue_cents` only went up once. This already worked because revenue counts the `paid` flag, so no code was needed for it.
- `pytest -q tests`: 71 passed, 5 runs in a row (66 existing, 5 new). The two failure-path tests fail on main's `app.py`; the other three pin behaviour that must not change.
- PR: <PR LINK>

**Decisions and reasons**
- Failure is opt-in through the request body, as #83 suggested, so the normal flow and the coming Pay button (#75) don't have to change.
- Used 402 like the unlock endpoint already does for an unpaid booking.
- A failed attempt is not stored anywhere (it is a mock); the booking just stays unpaid so it can be retried.

**Attempts and problems**
- #83 still says `create_booking` inserts `paid=True`, which was true before #74. We put the failure on the pay endpoint instead.
- Correction to Part 1: I wrote there that the flaky concurrency test was "not fixed yet". It already was (a deadlock now returns 409). The test passed 40 runs in a row on main.

**Shortcuts and unfinished work**
- There is no Pay button yet (#75), so the failure can only be triggered through the API, not the browser.
- Payment is still a mock: no provider, no amount charged.

**Help and tools**
- Used Claude Code to draft the change in `app.py` and the tests in `test_app.py`. I read the diff, checked that the failure tests fail on main's `app.py`, and re-ran the suite 5 times before pushing.

**Next steps**
- Action: #66 (confirmation page) and #75 (Pay button); the Pay button should show the "payment failed" message. Owner: Annabel and Gregory.

#### Part 5: Paid and unpaid bookings on the dashboard (issue #96)

**People and contributions**
- Annabel (business owner) picked #96 and assigned it to Flurina, who implemented it.

**Progress and evidence**
- `/dashboard` now shows "Paid bookings" and "Unpaid bookings" under the Bookings total, using the values `compute_metrics` has returned since #85.
- `pytest -q tests`: 73 passed, 5 runs in a row (71 existing, 2 new). Both new tests fail on main's `app.py`.
- PR: https://github.com/cs403bkk-2026/spacey/pull/98

**Decisions and reasons**
- Did this straight after #85 because the dashboard is due Tuesday and its single Bookings number was still ambiguous now that bookings start unpaid.
- The main test uses two paid and one unpaid booking, so swapped labels would be caught.

**Attempts and problems**
- None.

**Shortcuts and unfinished work**
- Still plain HTML with a handful of numbers, no styling or charts, in line with the "keep the UI basic" guidance.
- Revenue is still worked out from the space's current price (#78).

**Help and tools**
- Used Claude Code to make the two-line change and write the tests. I read the diff, checked the new tests fail on main's `app.py`, and re-ran the suite 5 times before pushing.

**Next steps**
- Action: the confirmation page with Pay and Unlock buttons (#66, #75) is on Gregory's branch `show_booking_conf`; needs a PR and review.

#### Part 6: Store the amount charged on the booking (issue #78)

**People and contributions**
- Annabel (business owner) picked #78 and assigned it to Flurina, who implemented it.

**Progress and evidence**
- Bookings now store `amount_cents`, copied from the space's price at the moment of booking. `/metrics` sums that column instead of joining to `spaces`, so a later price change no longer rewrites past revenue.
- Bookings that already exist get the space's current price filled in the next time the app starts, so revenue on the live system doesn't drop to zero when this deploys. The booking API responses did not change.
- `pytest -q tests`: 75 passed, 5 runs in a row (73 existing, 2 new). Both new tests fail on main's `app.py`.
- PR: https://github.com/cs403bkk-2026/spacey/pull/103

**Decisions and reasons**
- The column allows NULL on purpose: it is added to a table that already has rows, and NOT NULL would either break inserts from the older running version during a deploy or need a made-up default. Old rows are filled in on startup instead.
- Existing bookings get the space's current price because it is the best we have; we can't know what they were really charged.
- Did not show the amount in the booking responses yet, to keep the API shape (and Gregory's confirmation page in #100) unchanged.

**Attempts and problems**
- #78 says PATCH /spaces can change a price, but PATCH only updates name and capacity. So the issue's test ("change the price with PATCH") can't be written as it stands; the test changes the price directly in the database instead. Price editing through PATCH would be a separate issue.

**Shortcuts and unfinished work**
- The amount is still just the space's price. Pricing by duration is #80, and it will work out the amount in the one place where the booking is created.
- Cancelling and refunds (#82) don't use the amount yet, and nobody sees it on the confirmation page yet.

**Help and tools**
- Used Claude Code to draft the change in `app.py` and the tests in `test_app.py`. I read the diff, checked the new tests fail on main's `app.py`, and re-ran the suite 5 times before pushing. We also simulated the upgrade on a throwaway database (old code makes a paid booking, new code starts on it) to be sure existing revenue stays the same.

**Next steps**
- Action: #80 (price by duration) can now build on the stored amount. Owner: Annabel to prioritise.
- Action: decide whether PATCH /spaces should be able to change the price (new issue).

#### Part 7: Mocked subscriptions, not just pay-once (issue #101)

**People and contributions**
- Annabel (business owner) picked #101 and assigned it to Flurina, who implemented it.

**Progress and evidence**
- New `POST /members/<name>/subscribe` (mocked, always succeeds, subscribing again changes nothing) and a small `subscriptions` table. A member with an active subscription gets bookings that are created already paid, so they skip the Pay step and can unlock straight away. Members without a subscription go through the pay-once flow exactly as before.
- Names are matched trimmed and lower-case, so "Annabel" and "annabel " are the same subscriber.
- `pytest -q tests`: 91 passed, 5 runs in a row (83 existing, 8 new). 7 of the 8 new tests fail on main's `app.py`; the eighth guards the unchanged pay-once flow.
- PR: https://github.com/cs403bkk-2026/spacey/pull/109

**Decisions and reasons**
- This is the biggest gap against the brief ("pay once or subscribe"), so we took it before the smaller issues.
- A subscriber's booking is stored with amount 0: the subscription covers it, and charging the space price would count revenue that never moved.
- Kept it to the thin slice in the issue: no cancel, no price, no page to subscribe.

**Attempts and problems**
- `reset_tables` had to clear the new table as well; otherwise a subscription made in one test would still be there in the next and quietly change its result.

**Shortcuts and unfinished work**
- Subscription income is not modelled at all: there is no fee, so the dashboard shows nothing for it.
- Subscribing is API only; there is no page or button for it, and no way to cancel.
- Identity is still just a name (#86), so anyone can subscribe as anyone.

**Help and tools**
- Used Claude Code to draft the change in `app.py` and the tests in `test_app.py`. I read the diff, checked that the new tests fail on main's `app.py`, re-ran the suite 5 times, and ran the app on a throwaway database to click through a subscriber booking and a normal one before pushing.

**Next steps**
- Action: Annabel to confirm the amount-0 decision, and whether subscriptions need a price and a cancel next.
- Action: a way to subscribe from the browser (new issue).

#### Part 8: Let PATCH change a space's price (issue #105)

**People and contributions**
- Annabel (business owner) picked #105 and assigned it to Flurina, who implemented it.

**Progress and evidence**
- `PATCH /spaces/<id>` now also accepts `price_cents`; only the fields sent are changed. A booking made before a price change keeps the amount it was charged (revenue in `/metrics` doesn't move) and a booking made after is charged the new price. This is the test #78 originally asked for, now possible through the API.
- `pytest -q tests`: 79 passed, 5 runs in a row (75 existing, 4 new, 1 extended). Four of the tests fail on main's `app.py`.
- PR: https://github.com/cs403bkk-2026/spacey/pull/107

**Decisions and reasons**
- Followed #78 because a price can now be changed without rewriting past revenue.
- The price is checked with one shared rule for POST and PATCH (whole number, 0 or more, not true/false) instead of copying the old POST check.
- The error for an empty PATCH now reads "provide name, capacity and/or price_cents to update".

**Attempts and problems**
- Checking "the same rule as POST" against the real code turned up a bug: `POST /spaces` with `"price_cents": true` returned a 500. Python counts true as the number 1, so it got past the check and Postgres then refused it. Fixed by using the shared rule for POST too, with a test.

**Shortcuts and unfinished work**
- Anyone can change any price; there is no login or ownership check (#48, #86).
- No price history is kept, only the amount on each booking (#78).

**Help and tools**
- Used Claude Code to draft the change in `app.py` and the tests in `test_app.py`. I read the diff, checked the new tests fail on main's `app.py`, and re-ran the suite 5 times before pushing. Trying the "same rule as POST" wording against the real code with Claude Code is what turned up the `true` price bug.

**Next steps**
- Action: #106 (show the amount on the booking) once Gregory's confirmation page (#100) is merged.
- Action: Annabel to decide what counts as "in the past" for #102, and to prioritise #101 (subscriptions).

## 2026-09-22 - Day 9

#### Part 1: Add an OpenAPI specification (issue #113)

**People and contributions**
- Maksym asked for this before the handover; Annabel assigned it to Flurina.

**Progress and evidence**
- Added `openapi.yaml` documenting all 10 JSON endpoints - health, spaces (list/create/get/update/delete), space bookings, all bookings, pay, unlock, subscribe, and metrics - with request bodies, response shapes and status codes. Linked from `README.md`.
- Validated the file parses and validates as OpenAPI 3.0.3 with `openapi-spec-validator`. Hit every documented endpoint through the real app and compared actual responses against the spec; all matched.
- PR: https://github.com/cs403bkk-2026/spacey/pull/116

**Decisions and reasons**
- Documented only the JSON API, matching the issue's own endpoint list. The HTML pages (space list, booking form, confirmation page, dashboard) aren't part of it, since they return HTML, not JSON.
- Found while checking every response that booking replies don't include `amount_cents`, even though it's been stored since #78. Documented that gap and pointed at #106 rather than fixing it here, since that's a code change, not a docs one.

**Attempts and problems**
- None - reading the real code and testing every endpoint's actual response caught the amount_cents gap before it could make the spec wrong.

**Shortcuts and unfinished work**
- No request/response examples rendered as a browsable page (e.g. Swagger UI hosted somewhere) - README points people at pasting it into editor.swagger.io for now.

**Help and tools**
- Used Claude Code to read every route in `app.py`, write the spec, and check it. I reviewed the file and confirmed the endpoint-by-endpoint comparison against the real app before pushing.

**Next steps**
- Action: #106 (include amount_cents in booking responses), now that the spec makes the gap explicit.
- Action: Gregory/Annabel to pick the next issue.

#### Part 2: Show the amount charged on bookings and the confirmation page (issues #106, #114)

**People and contributions**
- Both are sub-issues of #117 (complete the payment flow); Flurina picked them up together since they touch the same page and data.

**Progress and evidence**
- `amount_cents` now appears on every booking response - create, get, list, list-per-space, pay, cancel.
- The confirmation page shows the total before paying and after: "Not paid yet - total $x.xx..." then "Paid. Total: $x.xx".
- `pytest -q tests`: 95 passed, 5 runs in a row (91 existing, 4 new, 2 fixed to include the new field). All 4 new tests fail on main's `app.py`.
- PR: https://github.com/cs403bkk-2026/spacey/pull/124

**Decisions and reasons**
- Did #106 and #114 as one PR since they are the same underlying data on the same page.
- Reused the amount already stored at booking time (#78), so a later price change or a subscriber's $0 booking both show correctly without new logic.

**Attempts and problems**
- Two existing tests asserted an exact booking dict and broke the moment `amount_cents` appeared. Fixed by adding the field to what they expect, rather than loosening the assertion.

**Shortcuts and unfinished work**
- The homepage's own space list doesn't show a total, only the confirmation page does.
- #117 (complete the payment flow) still isn't fully closed: no mocked card details are collected anywhere.

**Help and tools**
- Used Claude Code to add the field to every booking query and update the confirmation page, and to write the tests. I read the diff, confirmed the new tests fail on main's `app.py`, re-ran the suite 5 times, and rendered the page for a real booking before pushing.

**Next steps**
- Action: decide what's left to close #117 - mocked card details on the confirmation page, or is showing the price and paying enough for the "pay once" story. Owner: Annabel.

#### Part 4: Log in and log out (issue #122)

**People and contributions**
- Direct next step in #120 after #121 (registration). Flurina implemented it.

**Progress and evidence**
- `POST /login` (JSON and HTML form) and `POST /logout`, using Flask's session. A wrong password and an unknown email return the identical 401 `invalid email or password`, so a failed attempt can't be used to find out who has an account. The homepage shows Register/Login when logged out, or the logged-in email with a Logout button.
- `pytest -q tests`: 111 passed, 5 runs in a row (103 existing, 8 new). All 8 fail without the change.
- PR: https://github.com/cs403bkk-2026/spacey/pull/135 (stacked on the still-open #131, since login needs the users table)

**Decisions and reasons**
- `SECRET_KEY` follows the same env-var-with-a-dev-default pattern as `DATABASE_URL`; a comment says a real deployment must set a real one.
- The homepage nav clears a stale session (a user id that no longer exists, e.g. after a dev DB reset) instead of showing a broken logged-in state.

**Attempts and problems**
- First draft of two logout tests asserted a 200 JSON response, but a plain `client.post("/logout")` with no body isn't a JSON request, so it took the redirect branch and returned 302 - fixed by passing `json={}` where the test wants the JSON response, and keeping a separate test for the plain form/button path.

**Shortcuts and unfinished work**
- No "remember me" - the session is a plain cookie with no expiry set beyond Flask's default.
- No rate limiting on login attempts.
- Bookings still aren't linked to a user id, only a free-text member name - that's #86, and is what #123 ("My bookings" page) will need next.

**Help and tools**
- Used Claude Code to implement the routes and session handling and to write the tests. I confirmed the new tests fail against the register-branch baseline, re-ran the suite 5 times, and checked the whole flow with real cookies over HTTP (register, wrong password, unknown email, form login, the homepage reflecting the session, and the Logout button) before pushing.

**Next steps**
- Action: #123 ("My bookings" page), now that login exists - but it needs bookings linked to a real user id first, not just a name.
- Action: SECRET_KEY needs to be added to #47's environment variable list for the real deployment.
