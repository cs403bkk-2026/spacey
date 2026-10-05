# ADR 0002: Separate the browser client

Date: 2026-10-02

Status: Accepted decision; frontend delivered, backend UI cleanup and verification pending.

## Decision and rationale

Develop the browser client in [spacey-frontend](https://github.com/cs403bkk-2026/spacey-frontend).
The Frontend team should be able to review, test, release and roll back compatible
UI changes without a backend release. Explicit API contracts make the obligations
between client and providers visible.

The OpenAPI contract enabled the frontend to move quickly while keeping its
interface with the backend explicit. Extracting the browser client also allows
the main application to become smaller: remove server-rendered pages, form
handlers such as `book_from_form`, and duplicated presentation paths. Retain
the JSON HTTP API as the interface used by the frontend. Fewer entry paths
mean fewer places to maintain the same behaviour and fewer opportunities for
form and API behaviour to diverge.

Keep request parsing, authentication/session adaptation, JSON serialisation and
HTTP status mapping in `app.py`. Move business operations and their persistence
code towards the corresponding domain modules, retaining server-side business
rules and authorisation. This cleanup prepares clearer module boundaries;
it does not require immediate service extraction or a new framework.

Purchase, Payments and Access retain business rules, authorisation and authoritative
state. Frontend combines their capabilities into the member journey; it is not a
fourth backend bounded context. Separate deployment need not mean a separate
browser origin. The frontend delivery PR is merged; the owner reports the
frontend working at `/app/` as of 5 October. That report does not establish
completion of the backend cleanup or the release checks below.

## Alternatives

Keeping the UI in the monolith with clearer modules, or using a monorepo with
separate deployment units, would retain simpler local setup and atomic changes.
Separate repositories favour distinct delivery ownership but add contract checks,
release tooling and coordination for changes affecting both sides. Delivery
autonomy is an expected benefit to verify, not a consequence of moving files alone.

## Consequences

- Removing obsolete form handlers and server-rendered UI reduces presentation
  paths in the main application. The remaining backend still owns business
  rules, authorisation and authoritative data.
- Compatible UI changes can have a separate release cycle, but changes to API
  meaning, authentication or response shape require consumer/provider
  coordination. OpenAPI describes the promise; implementation checks must
  establish that both sides honour it.
- Separate builds, deployments and routing add operational work. Record which
  frontend/backend versions work together and how failures are diagnosed.
- Removing the server-rendered UI also removes that fallback. Recovery must
  retain a compatible frontend/API pair or deliberately restore the prior
  application UI; reverting either side alone may not restore the journey.
- A smaller controller layer makes domain-module extraction easier to reason
  about, but does not itself establish independent backend services or resolve
  data ownership.

## Work to be done

The frontend delivery PR is merged. The following cleanup and verification
items remain open in this record until supported by implementation evidence:

- [ ] Inventory the remaining HTML routes, templates, assets and form helpers,
  including `book_from_form`; check retained callers before deleting them.
- [ ] Remove obsolete server-rendered UI and duplicate form paths, preserving
  the JSON API and authentication behaviour used by the extracted frontend.
- [ ] Keep request/response adaptation in `app.py`; move business operations
  and persistence towards their corresponding domain modules without requiring
  a framework rewrite or immediate service split.
- [ ] Align OpenAPI and tests with retained behaviour and intentional removals;
  check success, validation errors and relevant authentication/failure cases.
- [ ] Verify booking, payment and access through `/app/` after cleanup, recording
  frontend/backend revisions and the environment.
- [ ] Demonstrate a compatible frontend-only release and recovery, including
  the recovery route after the old UI has been removed.
- [ ] Record ownership for contract changes, frontend delivery and routing,
  plus any changes that still require coordinated releases.

Use the existing frontend/backend work items to allocate this work. These
unchecked items are acceptance work, not evidence that a live check has failed.

## Migration and checks

Move one existing journey incrementally, reuse its design and keep the
server-rendered fallback until checked cutover. The next step is to remove
obsolete UI/form code after checking the retained frontend journey against the
JSON API. Update OpenAPI and tests for intentional interface changes, and check
that no retained caller depends on a removed route. No framework rewrite or
backend-for-frontend is implied.

Capacity and subscription cleanup follows separate gaps identified in the
glossary. This frontend decision does not itself define those product rules or
authorise discarding existing data; keep their behaviour and migration decisions
explicit in the corresponding changes.

Record frontend/backend revisions and verify the browser booking, payment and
access journey, including authentication and relevant failure states. Demonstrate
a compatible frontend-only release and rollback, and record where coordinated
changes remain necessary. Implementation and live checks have not passed merely
because this decision is accepted.

Assess simplification through the obsolete paths removed and the remaining
places where a rule must change, alongside the preserved member journey.
Deleted line counts alone do not demonstrate a better boundary.

References: [client scope #201](https://github.com/cs403bkk-2026/spacey/issues/201),
[frontend delivery proposal](https://github.com/cs403bkk-2026/spacey-frontend/pull/1).
