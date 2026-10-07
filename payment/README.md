# Payment team

The payment code is a package inside this app. A separate payment service has not started.

Ticket tracker: [https://docs.google.com/spreadsheets/d/1DAQPfFUgdsQBVuD7cuqFDiHtSwy2hnqWxvvAOs74ZAs](https://docs.google.com/spreadsheets/d/1DAQPfFUgdsQBVuD7cuqFDiHtSwy2hnqWxvvAOs74ZAs/edit?gid=0#gid=0)

## 1. What we own

| Person                 | GitHub                                        | Role              |
| ---------------------- | --------------------------------------------- | ----------------- |
| Yan Aung Hein          | [yaunghein](https://github.com/yaunghein)     | Software Engineer |
| Tom Everson            | [TomEverson](https://github.com/TomEverson)   | -                 |
| Hort                   | [lenghort](https://github.com/lenghort)       | -                 |
| Akarapong Thammawong   | [0xAkarapong](https://github.com/0xAkarapong) | -                 |
| Nicolas Piola Parucker | [NicolasPP](https://github.com/NicolasPP)     | -                 |
| Nika                   | —                                             | -                 |
| Maria                  | —                                             | -                 |

**We are responsible for**

- `POST /bookings/<id>/pay`: accept or reject the card, then record the outcome.
- Card rules for the mock: 13–19 digits, Luhn, expiry `MM/YY`, CVC of 3 or 4 digits. No payment provider.
- Storing the last 4 digits only. The full number and CVC stay out of the database.
- The `payments` table: status (`success`, `failed`, `unknown`), amount, currency (`USD`), reason, last 4, idempotency key.
- A second pay on an already paid booking returns that booking and does not take payment again.

**We need from other teams**

- Purchase: the booking and its amount, and a decision on who sets `bookings.paid`. Today Payment still writes `paid` and `card_last4` on `bookings`.
- Access: unlock stays closed until the booking is paid. Payment does not own the lock.

**Boundary still open.** After a failed payment the booking stays unpaid and can be retried. [PT-003](https://github.com/cs403bkk-2026/spacey/pull/230) says Purchase owns that update and a 15-minute hold, and Payment only reports the outcome. That pull request is still open, and Purchase has not confirmed the hold.

## 2. Current work and check

| Change                                                          | State     | What it improves                                                                                                |
| --------------------------------------------------------------- | --------- | --------------------------------------------------------------------------------------------------------------- |
| [PT-015 #209](https://github.com/cs403bkk-2026/spacey/pull/209) | Merged    | `pay_booking` lives in `payment/services.py`.                                                                   |
| [PT-007 #223](https://github.com/cs403bkk-2026/spacey/pull/223) | Merged    | Mock cards that fail Luhn are rejected.                                                                         |
| [PT-004 #231](https://github.com/cs403bkk-2026/spacey/pull/231) | Merged    | Routes, rules, and SQL are split inside `payment/`.                                                             |
| [PT-016 #236](https://github.com/cs403bkk-2026/spacey/pull/236) | Merged    | `payments` table and repository. Pay does not insert a row yet.                                                 |
| [#237](https://github.com/cs403bkk-2026/spacey/pull/237)        | Merged    | Payment package is on `main`. Approved by Maksym Prokopov.                                                      |
| [#205](https://github.com/cs403bkk-2026/spacey/pull/205)        | Merged    | First `payment` module.                                                                                         |
| [PT-008 #240](https://github.com/cs403bkk-2026/spacey/pull/240) | In review | Pay errors become `application/problem+json` with a `code`. No review yet.                                      |
| [PT-003 #230](https://github.com/cs403bkk-2026/spacey/pull/230) | In review | Failed-payment agreement. Documentation only.                                                                   |
| [PT-012 #232](https://github.com/cs403bkk-2026/spacey/pull/232) | In review | Logs the outcome without card data. Tom has commented.                                                          |
| [PT-005 #226](https://github.com/cs403bkk-2026/spacey/pull/226) | Open      | Boundary tests for card length, CVC, and expiry month. The tracker says Merged; the pull request is still open. |

## 3. Contributions

| Member                 | Contribution                                                                                                                         | Evidence                                                                                                                                                                                                                                                                                                     |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Yan Aung Hein          | Moved `pay_booking` into the payment service. Opened the structured error response. PT-011 (limit repeated failures) is not started. | [#209](https://github.com/cs403bkk-2026/spacey/pull/209) merged, [#240](https://github.com/cs403bkk-2026/spacey/pull/240) in review                                                                                                                                                                          |
| Tom Everson            | Luhn check, package split, `payments` table, and the domain merge. Boundary tests are still open.                                    | [#223](https://github.com/cs403bkk-2026/spacey/pull/223), [#231](https://github.com/cs403bkk-2026/spacey/pull/231), [#236](https://github.com/cs403bkk-2026/spacey/pull/236), [#237](https://github.com/cs403bkk-2026/spacey/pull/237) merged; [#226](https://github.com/cs403bkk-2026/spacey/pull/226) open |
| Hort                   | Started the move out of `app.py`. PT-004 is in his name; the merged pull request is Tom's.                                           | commit `33541de`, [PT-004](https://github.com/cs403bkk-2026/spacey/pull/231)                                                                                                                                                                                                                                 |
| Akarapong Thammawong   | Wrote the failed-payment agreement and the card-free logs. Neither is merged.                                                        | [#230](https://github.com/cs403bkk-2026/spacey/pull/230), [#232](https://github.com/cs403bkk-2026/spacey/pull/232)                                                                                                                                                                                           |
| Nicolas Piola Parucker | Created the payment module. PT-006 (fixed mock outcomes) is not started.                                                             | [#205](https://github.com/cs403bkk-2026/spacey/pull/205) merged                                                                                                                                                                                                                                              |
| Nika                   | No payment commit found. PT-009 is still Not Started. The table it asks about is already merged, and pay does not write it.          | tracker PT-009                                                                                                                                                                                                                                                                                               |
| Maria                  | No payment commit found. PT-010 (two pays at once) is Not Started.                                                                   | tracker PT-010                                                                                                                                                                                                                                                                                               |
