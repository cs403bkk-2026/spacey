-- PT-009: every payment attempt is a row. An attempt starts as 'unknown' (in
-- progress) and ends as 'success' or 'failed'. A booking may have at most one
-- attempt that is in progress or succeeded, so two concurrent collections
-- can't both charge: the second insert finds this index and gives way.
-- Failed attempts don't count, so a retry after a decline is a new row.
-- Safe to run more than once.
CREATE UNIQUE INDEX IF NOT EXISTS payments_one_open_or_paid_per_booking
  ON payments (booking_id)
  WHERE status IN ('success', 'unknown');
