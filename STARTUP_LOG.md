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