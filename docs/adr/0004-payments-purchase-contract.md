# ADR 0004: Payments–Purchase contract (PT-002)

Date: 2026-10-08

Author: Maria Yurkevich, Payments Product Owner

Status: Records the agreement confirmed by the Payments PO. Repository review and implementation verification are separate from agreement confirmation.

## Context

Purchase and Payments need a clear boundary inside the existing monolith. Payment processing must use Purchase's stored price, return an outcome and avoid duplicate collection. It must not update bookings or decide reservation eligibility.

This ADR records the Payments–Purchase working agreement based on Purchase's answers and clarifications from 5–6 October. It describes the target contract, not completed implementation.

## Decision

### Responsibilities

| Team | Owns |
|---|---|
| Purchase | Bookings, stored prices, payment eligibility, the 15-minute hold, booking updates, cancellation, refund amount and coordination with Access. Subscription coverage remains its responsibility while that code exists. |
| Payments | Mock card validation, payment records, mock collection, status lookup, duplicate protection, mock refunds and stored refund results. |
| Access | Issuing and revoking access when requested by Purchase. |

Payments receives the booking reference and amount from Purchase. It does not calculate booking prices or read/update booking records to make booking decisions.

### Function contract

For this increment, calls are functions within the monolith:

```text
collect(booking_id, amount_cents, card)
    -> {status: paid|failed, payment_id, error}

payment_status(booking_id)
    -> {status: paid|failed|none, payment_id}

refund(booking_id, amount_cents, reason)
    -> {status: succeeded|failed, refund_id, amount_cents, error}
```

Amounts use integer USD cents: 4500 means $45.00. Card input contains card_number, expiry in MM/YY format and cvc. Never store or log full card numbers or CVCs; last four digits may be stored.

Results return directly to Purchase. Payments does not call Purchase back. This replaces the callback/notification direction described in ADR 0003's "Payment attempt and outcome notification" section. ADR 0003's booking ownership, hold and late-success rules remain applicable. HTTP endpoints and asynchronous notification are outside this function contract.

### Collection and retries

- Purchase checks the booking's eligibility and hold before requesting collection.
- Payments records successful collection and returns its result. Purchase updates its own booking and requests access.
- A confirmed failure returns a short reason. Purchase keeps the booking unpaid; no access is granted. The member may try again.
- booking_id identifies collection for a booking; no separate request idempotency key is required for this increment.
- At most one successful collection is allowed per booking. After success, repeats return the same stored success and payment ID without another collection.
- A repeat after confirmed failure is a new attempt. The rule "same booking_id returns the stored result" must not prevent this retry.
- Purchase does not require earlier failure history. Payments chooses the record model while supporting status lookup and retries.
- Concurrent calls must not both complete successful collection. A lookup key alone is insufficient; the implementation must make this protection atomic.

### Unknown outcomes

A lost response or timeout does not establish failure. Purchase checks payment_status first and must not grant access while success is unconfirmed. Repeating collection must preserve the no-duplicate rule.

The proposed collect return values are paid and failed. An unknown transport outcome must not be silently converted to failed. Likewise, none must not be used as proof that no concurrent collection is in progress.

### Hold and late success

Purchase owns the 15-minute hold, measured from booking creation. Retries do not restart it. Payments has no booking-expiry timer.

Payments records late collection as normal success. Purchase checks whether it can still confirm the booking and whether the slot is free. Otherwise, Purchase requests a full refund.

### Subscription coverage

Subscription support was reported as still present in the code, although excluded from the current teaching scope. This ADR does not remove it. Purchase handles coverage and does not request collection for a covered booking. Payments must not create a fictional payment for coverage or invent missing historical payment details.

### Refunds

Mock refunds follow the payment-record increment. Purchase cancels the booking, requests access revocation and calls Payments for a refund.

- Full refunds only for now; keep amount_cents in the interface for future partial refunds.
- Purchase chooses the amount. Payments validates it against the stored collection and rejects an amount exceeding what was collected.
- Repeating the same refund request returns the stored result without another refund. A different second refund for the same booking is refused.
- Payment and refund records remain available by booking reference after booking cancellation; they must not depend on the booking row surviving.

## Consequences

Purchase can change booking policy without placing booking updates in Payments. Payments can add storage and duplicate protection behind the agreed function boundary. Purchase must consume the returned outcomes and coordinate booking/access changes.

Implementation must specify exact null/error fields, behaviour for changed inputs, in-progress status lookup and failed-refund retries consistently with these rules. This ADR does not introduce additional decisions for those details or claim that they are implemented.

This contract supersedes ADR 0003's callback direction and its open question about the collection lookup key. No real payment provider, independent service deployment or full layering rewrite is required by this increment.

## Verification requirements

These are acceptance requirements, not executed results:

- Valid mock payment produces one stored success; invalid or declined input returns failure.
- Retry after failure can succeed; repeat after success returns the same payment ID.
- Concurrent calls produce at most one successful collection.
- Lost responses can be resolved without duplicate collection or access on unconfirmed payment.
- Covered bookings create no fictional payments; late success is handled by Purchase confirmation or a full refund.
- Repeated refunds do not refund twice; excessive or different second refunds are rejected.
- Records and logs contain no full card numbers or CVCs.

Use an additive, versioned migration, rehearse it on disposable empty and populated data, run the affected package suite and coordinate the API journey with Purchase. PT-010's controlled test documents a race; it is not evidence of a completed fix.

## References

- Purchase answers, subsequent clarifications and function interface supplied on 5–6 October 2026; agreement confirmation reported by Maria Yurkevich on 8 October. The original message links were not supplied.
- Instructor's "Payments, 1 October studio" brief supplied in the discussion.
- [ADR 0003: Booking after failed or unknown payment](0003-booking-after-failed-payment.md).
- [PT-010 concurrency test, PR #242](https://github.com/cs403bkk-2026/spacey/pull/242).

