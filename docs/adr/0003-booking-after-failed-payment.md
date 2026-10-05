# ADR 0003: Booking after failed or unknown payment (PT-003)

Date: 2026-10-05

Status: Proposed; retry and ownership rules agreed in the supplied contract.
Purchase confirmation of the hold policy and unresolved boundaries is pending.

## Decision

Payment returns success, failed, or unknown. Purchase owns the booking and
enforces its unpaid slot hold. Payment records payment outcomes and never
changes bookings or releases slots.

- Failed: Purchase keeps the booking unpaid. The member can try again on the
  same booking at the original price while its hold remains active.
- Unknown (for example, a timeout): Purchase keeps the booking unpaid and asks
  Payment again about the same operation. An unknown result may hide a successful
  charge, so checking or retrying must not create another charge.
- Success: Payment returns payment_id, booking_id, amount_cents, and currency.
  Purchase marks its booking paid and asks Access for the code. A repeat of the
  successful payment operation returns the same result without charging again.

Unpaid bookings cannot unlock the space and contribute no revenue. A failed
attempt alone does not cancel the booking or release its slot.

Purchase has suggested a 15-minute unpaid slot hold. Purchase must confirm its
duration, when the clock starts, and the expiry behavior before implementation.
Retries must not silently extend the hold. Once an unpaid hold expires, Purchase
releases the slot; the member must create a new booking subject to availability.
An unknown payment at expiry needs the reconciliation decision below before this
release rule can be implemented safely.

## Reason and consequences

Keeping the booking allows the member to correct a failed payment without losing
the reservation immediately. A finite hold prevents abandoned unpaid bookings
from reserving slots indefinitely. Keeping booking changes in Purchase gives one
team ownership of booking state and availability.

This is a target policy, not evidence that expiry or the new payment contract is
implemented. The existing mock keeps failed bookings unpaid and retryable but
does not automatically expire them. This PR changes documentation only.

## Questions for Purchase and Payment

- Identify repeat operations by booking_id or a separate idempotency key. The
  identity must distinguish a new attempt after failure from a repeat after
  success or unknown.
- Confirm the 15-minute hold, its start time, and Purchase's enforcement.
- Define reconciliation when payment succeeds but Purchase learns about it
  after the hold expires, including when another member has booked the slot.
  Do not grant access to an expired booking automatically.

## Acceptance criteria for implementation

- Failure preserves the unpaid booking, its ID, price, and active slot hold;
  a later attempt can succeed before expiry.
- Unknown keeps the booking unpaid; repeating the operation resolves its status
  without charging twice.
- Success lets Purchase mark the booking paid and request access. An already
  paid booking is not expired by the unpaid hold rule.
- Expiry releases an unpaid slot according to the confirmed policy. An expired
  booking cannot be paid or unlocked through the ordinary retry path.
- Repeated successful requests return the same payment result and count revenue
  once, including concurrent requests.

## Related tickets

PT-002 records the full Payment → Purchase contract. PT-006 adds a mock unknown
outcome; PT-008 defines structured outcomes; PT-009 stores payments; PT-010 checks
concurrent retries; PT-014 migrates booking writes out of Payment. Purchase owns
the hold implementation. Refund on cancellation belongs to PT-013 and does not
change the failed-payment decision here.

Source: [SDLC Ticket Tracker, Sprint-1](https://docs.google.com/spreadsheets/d/1DAQPfFUgdsQBVuD7cuqFDiHtSwy2hnqWxvvAOs74ZAs/edit#gid=0)
and the supplied agreed contract. PT-003 owner: Drake.
