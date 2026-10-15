# Startup app

You are the founding engineering team. Build a working system by Friday 25 September in which a
paying member can find a space, book it, pay once or subscribe, and receive access through an
API-driven lock.

This repository deliberately starts with delivery plumbing and almost no product. The product
design, architecture, data model, and work split are yours.

## Start locally

Requires Python 3.12 and Docker.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d --wait db purchase
DATABASE_URL=postgresql://spacey:spacey@localhost:5433/spacey PURCHASE_URL=http://localhost:8002 PURCHASE_TOKEN=dev-token pytest
DATABASE_URL=postgresql://spacey:spacey@localhost:5433/spacey PURCHASE_URL=http://localhost:8002 PURCHASE_TOKEN=dev-token flask --app app run --port 5001 --debug
```

The health check is at <http://127.0.0.1:5001/health>. This process is the JSON API.
The browser client is the separate [spacey-frontend](https://github.com/cs403bkk-2026/spacey-frontend)
app, served at `/app/` on the shared host. `GET /` redirects there.

A few things that trip people up the first time:

- **Port 5433, not 5432.** `compose.yaml` maps the database container to host port 5433, not
  Postgres's usual 5432 - that's so it doesn't collide with a Postgres already installed on your
  laptop (this happened to us). `DATABASE_URL` must say `5433` when running locally like above.
- **Port 5001, not 5000.** On macOS, port 5000 is normally taken by AirPlay Receiver, so Flask's
  default port fails silently or serves the wrong thing. Use `--port 5001` (or any other free
  port) instead.
- **If `flask run` exits with `Could not connect to the database`**, Postgres isn't running yet -
  run `docker compose up -d --wait db purchase` first. See [Configuration](#configuration) below for every
  variable this app reads.

To exercise the full container stack instead (app + database together, closer to the deployed
setup):

```sh
docker compose up --build
```

Then the API is at <http://127.0.0.1:8000/>. `GET /health` reports status, and `GET /` redirects to `/app/`.

## Configuration

Payment logs include only booking ID and fixed outcomes. Set `LOG_LEVEL=DEBUG`
to include payment start events; the default is `INFO`. Expected rejections use
`WARNING`; database failures use `ERROR` without database diagnostics or card data.

The app reads these environment variables. `PURCHASE_URL` and `PURCHASE_TOKEN` are required; the
others have development-only defaults, but a real deployment should set all of them explicitly.

| Variable            | What it's for                                                                 | Default (local only)                              |
|----------------------|-------------------------------------------------------------------------------|-----------------------------------------------------|
| `DATABASE_URL`       | Where to find Postgres.                                                       | `postgresql://spacey:spacey@localhost:5432/spacey`  |
| `APP_REVISION`       | Shown by `GET /health`, so a deployment can confirm which commit is live.     | `local`                                              |
| `RESET_DB_ON_START`  | If `true`, wipes all tables on startup. Used by tests; never set this in a real deployment or you will delete real data. | `false` |
| `SECRET_KEY`         | Signs the login session cookie. **Must** be set to a real secret in any deployment - the default is public (it's printed right here in this file), so anyone could forge a session cookie claiming to be any user. The app would still run fine without it set, which is exactly what makes this easy to forget. | `dev-secret-key-not-for-production` |
| `REPORTING_URL`      | Where `GET /dashboard` redirects (the Grafana report). | `https://grafana.cs403bkk26.space/d/spacey-reporting` |
| `PURCHASE_URL`       | The Purchase service (spacey-purchase), which the `purchase/` functions call. Required. Unset or empty: every Purchase route answers 503. If the service cannot answer, those routes answer `503 {"error": "purchase unavailable"}` too. | none (`http://localhost:8002` with compose) |
| `PURCHASE_TOKEN`     | The bearer token sent to the Purchase service. Set only in the Nomad variable `nomad/jobs/spacey` (`purchase_token`); never committed. Local runs and CI use `dev-token` (`compose.yaml`). | empty |

`/pay` follows one more flag, the column `pays` on the switch row `purchase_switch` (PUR-027),
which the Purchase team sets with its own database login. `false` (the default): `/pay` charges
here, as before. `true`, with `PURCHASE_URL` set: `/pay` goes to the Purchase
service, which charges through Payments' API; the hub mirrors the paid row. It is read on every
call, so a change takes effect at once, with no restart. A paid cancel is refunded here only when
the service refunded nothing (Payments holds no charge for the booking, or the service has no
Payments settings), so a booking charged here before the flag is still refunded here.

A missing or unreachable `DATABASE_URL` now fails fast at startup with a short, readable message
instead of a raw stack trace.

## How changes reach the live system

1. Create a branch and open a pull request.
2. GitHub Actions installs dependencies and runs the tests.
3. After review, merge the pull request to `main`.
4. Once the deployment environment is enabled, GitHub Actions builds the exact merged revision,
  publishes its container image, and submits the Nomad job.
5. Check the permanent URL and its `/health` response. `revision` must equal the merged commit.

Direct pushes to `main` are blocked. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Architecture decisions

- [ADR 0001: Move reporting to Grafana](docs/adr/0001-move-reporting-to-grafana.md)
- [ADR 0002: Separate the browser client](docs/adr/0002-separate-frontend-repository.md)

## Modules

### Purchase (`purchase/`)

- **Data:** `spaces`, `bookings`, `subscriptions`, `users`. `purchase/schema.py` also creates
  `access` and `bookings.card_last4`, which other modules use.
- **Rules:** a booking's end is after its start, party size is 1 to the space's capacity, and
  bookings for the same space can't overlap (back-to-back is fine; Postgres also enforces this
  with `no_overlapping_bookings`). The price is the hourly rate prorated to the booked time and
  saved on the booking. A subscriber's booking is paid at once and costs 0. A blank member name
  becomes `guest`.
- **Dependencies:** Postgres (with `btree_gist`); `app.py` calls into it for every route.
- **Open boundary:** schema setup still covers tables that belong to other modules.

### Payment (`payment/`)

#### Agreed architecture with Purchase

Payments only handles payments: it validates mock card details, processes and records mock
payments, and returns a success, failed or unknown outcome to Purchase. It does not read or
update bookings. Purchase owns booking prices, booking updates and requests to Access.

- **Data:** the `payments` table (migration `001_create_payments.sql`) only. Amounts are
  integer USD cents (`amount_cents`: 4500 = $45.00).
- **Rules:** after a failure another attempt is allowed; after a success a repeated operation
  returns the same result without creating another payment. Unknown outcomes are reported
  separately from failures. Full card numbers and CVCs are never stored or logged, and
  unknown historical details are preserved.
- **Interface:** Purchase sends `booking_id`, `amount_cents`, `currency` (USD),
  `card_number`, `expiry` and `cvc`. Payments returns success (`payment_id`, `booking_id`,
  `amount_cents`, `currency`), failure with a reason, or an unknown outcome.
- **Purchase's side:** after a success, Purchase marks its own booking paid and requests an
  access code from Access. After a failed or unknown outcome it keeps the booking unpaid and
  grants no access.

#### Current implementation

- **Data:** every attempt that reaches the mocked provider is a row in `payments` (PT-009). It
  starts as `unknown` (in progress) and ends as `success` or `failed`. A unique index
  (migration `003_one_open_payment_per_booking.sql`) allows at most one `unknown` or `success`
  row per booking. Refunds are rows too (`refunded`).
- **Rules:** the card needs 13-19 digits, a valid Luhn checksum, a 3-4 digit CVC and an
  unexpired `MM/YY` expiry; invalid details are refused before any attempt and leave no row.
  Only the last 4 digits are stored. A booking is charged at most once, even by concurrent
  requests: the second request meets the first one's row and is answered from it. A decline
  is stored as `failed`, and paying again is a new attempt. A provider that gives no answer
  leaves the row `unknown`; that is never treated as a failure, and nothing is charged again
  while it stays unknown. A free booking (0 cents) stores nothing. The provider is mocked.
- **Interface:** `payment.services.collect(db, booking_id, amount_cents, card_number, expiry,
  cvc)` returns `{status: paid|failed|unknown, payment_id, error}`, and `payment_status(db,
  booking_id)` returns `{status: paid|unknown|failed|none, payment_id}`. Purchase
  (`purchase.booking.mark_booking_paid`) calls only `collect`, then updates its own booking:
  200 on `paid`, 400 or 402 on `failed`, 504 on `unknown` (booking left unpaid).
- **Dependencies:** none on `bookings`; Payments never reads or updates them. Access
  (`/unlock`) and `/metrics` rely on Purchase's `bookings.paid`.
- **Still open:** settling an `unknown` attempt needs a provider status check, which the mock
  doesn't have, so such a booking stays unpaid until that exists.

## API reference

Every JSON endpoint is documented in detail in [openapi.yaml](openapi.yaml) (OpenAPI 3.0) - request
bodies, response shapes, status codes. Paste its contents into <https://editor.swagger.io> for a
browsable version, or view it with any OpenAPI tool.

Two routes redirect instead of returning JSON, so they are not in that document:
`GET /` sends the browser to the frontend at `/app/`, and `GET /dashboard` sends it to Grafana.

Quick summary of the JSON API (see [openapi.yaml](openapi.yaml) for the full detail):

| Method | Path                              | What it does                                                        |
|--------|------------------------------------|----------------------------------------------------------------------|
| GET    | `/health`                          | App + database health check                                          |
| GET, POST | `/spaces`                       | List spaces / create a space                                         |
| GET, PATCH, DELETE | `/spaces/<id>`          | Get, update, or delete one space                                     |
| GET, POST | `/spaces/<id>/bookings`         | List a space's bookings / book it                                    |
| GET    | `/bookings`                         | List every booking                                                   |
| GET, DELETE | `/bookings/<id>`               | Get or cancel one booking                                            |
| POST   | `/bookings/<id>/pay`                | Pay a booking (mocked; `force_failure: true` tests the failure path) |
| POST   | `/bookings/<id>/unlock`             | Get the access code for a paid booking (mocked lock)                 |
| POST   | `/members/<name>/subscribe`         | Removed; always answers 410                                          |
| POST   | `/register`                         | Create an account (email + password, hashed)                        |
| POST   | `/login`, `/logout`                 | Start or end a session                                               |
| GET    | `/metrics`                          | Business metrics as JSON                                             |

A booking made while logged in is linked to that account (`user_id` on the booking); one made
while logged out is a guest booking (`user_id: null`).

The live URL and deployment-log link will be added here before students are invited.

## Start useful work

Do not wait for the kickoff meeting.

1. Open one issue describing the thinnest member journey you can deliver end to end.
2. Split that journey into the first three owned tasks without assigning permanent roles.
3. Each team member opens or reviews at least one pull request.
4. Merge one small user-visible change and verify its revision at the permanent URL.
5. Append the first entry to [STARTUP_LOG.md](STARTUP_LOG.md).
6. Post unresolved blockers in Slack using the format in
  [CONTRIBUTING.md](CONTRIBUTING.md).

## Keep secrets out of GitHub

This repository is public. Never commit `.env`, credentials, tokens, or private keys. Deployment
credentials live in GitHub Actions or the runtime platform, not in the repository.
