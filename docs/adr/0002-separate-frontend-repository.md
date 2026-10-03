# ADR 0002: Separate the browser client

Date: 2026-10-02

Status: Accepted decision; migration and verification pending.

## Decision and rationale

Develop the browser client in [spacey-frontend](https://github.com/cs403bkk-2026/spacey-frontend).
The Frontend team should be able to review, test, release and roll back compatible
UI changes without a backend release. Explicit API contracts make the obligations
between client and providers visible.

Purchase, Payments and Access retain business rules, authorisation and authoritative
state. Frontend combines their capabilities into the member journey; it is not a
fourth backend bounded context. Separate deployment need not mean a separate
browser origin. The proposed `/app/` routing still needs agreement.

## Alternatives and consequences

Keeping the UI in the monolith with clearer modules, or using a monorepo with
separate deployment units, would retain simpler local setup and atomic changes.
Separate repositories favour distinct delivery ownership but add contract checks,
release tooling and coordination for changes affecting both sides. Delivery
autonomy is an expected benefit to verify, not a consequence of moving files alone.

## Migration and checks

Move one existing journey incrementally, reuse its design and keep the
server-rendered fallback until checked cutover. No framework rewrite or
backend-for-frontend is implied.

Record frontend/backend revisions and verify the browser booking, payment and
access journey, including authentication and relevant failure states. Demonstrate
a compatible frontend-only release and rollback, and record where coordinated
changes remain necessary. Implementation and live checks have not passed merely
because this decision is accepted.

References: [client scope #201](https://github.com/cs403bkk-2026/spacey/issues/201),
[frontend delivery proposal](https://github.com/cs403bkk-2026/spacey-frontend/pull/1).
