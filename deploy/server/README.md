# Deploying to social.stravica.nl (server with nginx already on 80/443)

The stock `docker-compose.yml` ships Caddy on ports 80/443. This server already runs nginx there, so the override in
this folder turns Caddy off and publishes the web app and the API on loopback only; nginx proxies to them and certbot
issues the certificate.

## One command (temporary domain first)

```bash
git clone git@github.com:Naifnajm/social-ai-web.git /opt/stravica-social
cd /opt/stravica-social && git checkout deploy/social-stravica-nl
bash deploy/server/deploy.sh
```
With no argument the site goes live on `https://social.51.75.27.21.nip.io` (nip.io resolves to the server IP, so no
DNS record is needed). The script creates `.env` with random secrets (mode 600), builds, starts, waits for health,
writes the nginx site (after `nginx -t`) and asks certbot for the certificate. On later runs it backs up the database
first.

## Switch to the real subdomain

1. GoDaddy → stravica.nl → DNS: `A` record, name `social`, value `51.75.27.21`.
2. `bash deploy/server/deploy.sh social.stravica.nl` — updates `.env`, the nginx site and the certificate; data and
   secrets stay. Then update the redirect/webhook URLs registered at Meta, Stripe, etc.

## After the first start

- Platform admin: see "Platform administrator account and password" below.
- Backups: add the cron line from `backup.sh`.

## Platform administrator account and password

Run these on the server from the repository folder (`cd /opt/stravica-social`). The API service of the compose
project is called `api`; its image has `python` (and `uv`) with the app installed, so `python -m` works directly.
`docker compose exec` gives the command a terminal, so passwords are typed at a hidden prompt: they never appear on
screen, in the shell history or in any log.

```bash
cd /opt/stravica-social
DC="docker compose -f docker-compose.yml -f deploy/server/docker-compose.server.yml"

# Is there an active platform administrator? (their e-mails and last sign-in)
$DC exec api python -m app.modules.billing.cli check

# First time: create your administrator account (asks for the password twice)
$DC exec api python -m app.modules.billing.cli create-superadmin you@example.com --name "Your name"

# Set or reset the password of any account (asks twice; signs that account out everywhere, marks the e-mail
# confirmed). Rules: at least 12 characters, not a common password, not like the e-mail address.
$DC exec api python -m app.modules.billing.cli set-password you@example.com

# Or let the server generate a strong password, printed once (store it in a password manager)
$DC exec api python -m app.modules.billing.cli set-password you@example.com --generate

# Other administrators
$DC exec api python -m app.modules.billing.cli list-superadmins
$DC exec api python -m app.modules.billing.cli create-superadmin colleague@example.com   # existing account: promoted
$DC exec api python -m app.modules.billing.cli revoke-superadmin colleague@example.com   # never the last active one
```

`--password …` still works for scripts but prints a warning: the value stays in the shell history. After signing
in, turn on two-step sign-in in Account › Security. Then everything about users is in Admin › Users (search and
filters, CSV, per-user page with workspaces, keys, apps, activity; temporary password, reset e-mail, sign out
everywhere, revoke keys and apps, memberships and ownership transfer, "view as" for 30 minutes, export, delete).

Update later: `cd /opt/stravica-social && git pull && bash deploy/server/deploy.sh`.
Roll back: `git checkout <previous commit> && bash deploy/server/deploy.sh`; restore data with
`pg_restore -U stravica -d stravica --clean` from `/var/backups/stravica-social`.

Ports 3110 / 8110 were free in the last server snapshot; `deploy.sh` stops if they are taken.

## AI assistants (Claude, ChatGPT) and the MCP endpoint

The API serves the remote MCP server at `https://<domain>/mcp` and its own OAuth 2.1 sign-in at `/oauth2/*` with
discovery documents at `/.well-known/oauth-authorization-server` and `/.well-known/oauth-protected-resource[/mcp]`.
The nginx site above routes these to the API (with buffering off for `/mcp`); after pulling, re-run `deploy.sh` (or
copy the site file and `nginx -t && systemctl reload nginx`). `SAI_PUBLIC_API_URL` must be the public https origin
(it is the OAuth issuer and the MCP resource identifier). Nothing else to configure: customers add the URL as a custom
connector in Claude or ChatGPT and sign in with their Stravica account (Settings › Connected apps & API explains it).
