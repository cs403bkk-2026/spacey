-- The access code handed out when a booking is unlocked (#171).
-- One code per booking, kept so a page refresh shows the same code
-- instead of a new one. ON DELETE CASCADE because cancelling a
-- booking deletes its row, and the code is worthless without it.
-- Runs after Purchase's tables exist, since it references bookings.
-- Safe to run more than once.
CREATE TABLE IF NOT EXISTS access (
  booking_id  INTEGER PRIMARY KEY
              REFERENCES bookings (id) ON DELETE CASCADE,
  access_code TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
