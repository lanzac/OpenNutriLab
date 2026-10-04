# Deployment

This describes running OpenNutriLab on a single Docker host: a VPS from
OVHcloud, Hostinger, Scaleway, Hetzner or anywhere else that gives you a Linux
machine, root access and a public IP.

> [!WARNING]
> A _shared hosting_ plan is not enough. Those are built for PHP and give you
> no way to run Docker, PostgreSQL, Redis or a long-lived Python process. Look
> for a plan described as **VPS**, **cloud instance** or **dedicated server**.

Nothing below is specific to a provider. The application reads every
host-specific value from its environment, so the same image runs on any of
them, and on a managed container platform too.

## What the stack contains

| Service    | Role                                                                                                                                                                             |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `caddy`    | Terminates TLS, obtains and renews the Let's Encrypt certificate automatically, serves `/media/` and forwards everything else to Django. The only service that publishes a port. |
| `django`   | The ASGI application under uvicorn. Runs migrations on start.                                                                                                                    |
| `postgres` | The database, on a named volume.                                                                                                                                                 |
| `redis`    | Cache.                                                                                                                                                                           |

Static files are not a service. `collectstatic` runs while the image is built,
and WhiteNoise serves the hashed bundle from inside the Django process with the
right cache headers.

## Prerequisites

1. A VPS running a recent Linux, with Docker Engine and the Compose plugin
   installed.
2. A domain name with an `A` record (and `AAAA` if you have IPv6) pointing at
   the server's IP. Caddy cannot obtain a certificate before DNS resolves.
3. Ports 80 and 443 reachable from the internet. Port 80 is not optional: the
   ACME HTTP challenge uses it.

## First deployment

Clone the repository onto the server:

```sh
git clone <repository-url> opennutrilab
cd opennutrilab
```

Create the three environment files. None of them is tracked by git.

**`.envs/.production/.django`**: copy the template and fill it in:

```sh
cp .envs/.production/.django.example .envs/.production/.django
```

Generate the secret key with:

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Set `DJANGO_ALLOWED_HOSTS` to your domain. The settings have no default for
either: the process refuses to start rather than run with a guessable key.

**`.envs/.production/.postgres`**: same idea:

```sh
cp .envs/.production/.postgres.example .envs/.production/.postgres
```

**`.env`** at the repository root, read by Compose itself:

```sh
DOMAIN_NAME=opennutrilab.example
ACME_EMAIL=you@example.com
```

Then build and start:

```sh
just prod-build
just prod-up
```

Create the first account:

```sh
just prod-manage createsuperuser
```

Load OpenFoodFacts' ingredient taxonomy, a dictionary that gives the English
and French names of what a label names, and a CIQUAL hint (it downloads about
3 MB, takes a few seconds, and can be run again at any time to refresh it):

```sh
just prod-manage import_off_taxonomy
```

Ingredients are read from the label's text, which does not need it. Until it has
run, an ingredient has no English name (it is named as the label words it, and
the English name is added when the reference is reviewed), and the proposals of
CIQUAL foods lose their second signal.

Load ANSES' CIQUAL food composition table, the reference data nutrient
estimates are built on (licence Etalab 2.0: the attribution it stores must be
shown wherever its data is). It downloads about 70 MB, which takes several
minutes, then writes about 215,000 values in under a minute. Prepared dishes,
sauces and stocks are left out. It can be run again at any time, and adds
nothing twice:

```sh
just prod-manage import_ciqual
```

To avoid the download, give it a directory that holds the four XML files of a
release (`alim`, `alim_grp`, `compo` and `const`, each named with its date,
from https://doi.org/10.57745/RDMHWY) with `--path`.

Watch the first boot; Caddy logs the certificate it obtains:

```sh
just prod-logs
```

## Updating

```sh
just prod-deploy
```

That pulls, rebuilds the image and restarts. Migrations run from the
container's start script, so there is no separate step.

## Email is not optional

`ACCOUNT_EMAIL_VERIFICATION` is set to `"mandatory"` in
`config/settings/base.py`. Until `EMAIL_HOST` and its companions point at a
working SMTP server, **nobody can complete a signup**: the confirmation mail is
never delivered. Password resets fail the same way.

Any transactional mail provider works, as does a mailbox at your registrar.

## HSTS: raise it slowly

`DJANGO_SECURE_HSTS_SECONDS` starts at 60 on purpose. HSTS cannot be revoked: a
browser that has seen the header refuses plain HTTP to your domain for the
whole duration, whatever you change afterwards. Once HTTPS has been stable for a
while, raise it in steps: 3600, then 86400, then 31536000.

## Using a managed database

Providers sell managed PostgreSQL, which handles backups and upgrades for you.
To use one, set in `.envs/.production/.postgres`:

```sh
DATABASE_URL=postgres://user:password@host:5432/dbname
DJANGO_DATABASE_SSL_REQUIRE=True
```

The entrypoint leaves an existing `DATABASE_URL` alone, so nothing else
changes. Remove the `postgres` service from the compose file and drop it from
the `depends_on` of `django`.

## Backups

With the bundled database, the maintenance scripts inherited from
`compose/production/postgres/` are available:

```sh
just prod-backup     # dump into the backups volume
just prod-backups    # list the dumps
```

They write inside a Docker volume on the same machine as the data, which is not
a backup in any meaningful sense. Copy the dumps off the server on a schedule,
or use a managed database and let the provider handle it.

## Serving the mobile app

The API lives under `/api/v1/`; its documentation, at `/api/v1/docs`, is
reserved to staff accounts. Every route needs a signed-in user:

- the site's own pages use the Django session cookie (with CSRF on writes);
- a mobile client signs in through django-allauth's headless API, under
  `/_allauth/app/v1/` (`auth/login`, `auth/signup`, ...), and sends the session
  token it receives in an `X-Session-Token` header on every API call.

`ACCOUNT_EMAIL_VERIFICATION` is mandatory for those accounts too, so the SMTP
settings above must work before anyone can sign in from the app.

Both `/api/` and `/_allauth/` are matched by `CORS_URLS_REGEX`. Browsers and web
views are what enforce CORS; a native HTTP client sends no `Origin` header and
needs nothing configured. If the mobile app runs in a web view (Capacitor, for
instance) add its origin:

```sh
DJANGO_CORS_ALLOWED_ORIGINS=capacitor://localhost,https://app.opennutrilab.example
```

## What this does not cover

- **No continuous deployment.** CI builds the production image on every push
  but never pushes it to a registry. Deploying is `just prod-deploy` on the
  server.
- **One host only.** `/start` runs `migrate` before booting, which two
  containers starting at once would race. Move migrations to a one-off job
  before running more than one replica.
- **No error tracking.** Unhandled exceptions go to the container logs and
  nowhere else. Sentry is the usual next step.
- **No rate limiting** in front of the login and API endpoints.
