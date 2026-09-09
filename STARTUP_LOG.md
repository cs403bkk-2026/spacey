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