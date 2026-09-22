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
pytest
flask --app app run --debug
```

Open <http://127.0.0.1:5000/>. The deployment health response is at
<http://127.0.0.1:5000/health>.

To exercise the container instead:

```sh
docker compose up --build
```

Then open <http://127.0.0.1:8000/>.

## How changes reach the live system

1. Create a branch and open a pull request.
2. GitHub Actions installs dependencies and runs the tests.
3. After review, merge the pull request to `main`.
4. Once the deployment environment is enabled, GitHub Actions builds the exact merged revision,
   publishes its container image, and submits the Nomad job.
5. Check the permanent URL and its `/health` response. `revision` must equal the merged commit.

Direct pushes to `main` are blocked. See [CONTRIBUTING.md](CONTRIBUTING.md).

## API reference

Every JSON endpoint is documented in [openapi.yaml](openapi.yaml) (OpenAPI 3.0). Paste its contents into <https://editor.swagger.io> for a browsable version, or view it with any OpenAPI tool. A few routes render HTML pages for a browser instead (the space list, the booking form, the booking confirmation page, `/dashboard`) and are not part of that document.

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
