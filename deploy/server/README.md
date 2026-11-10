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

- Platform admin: `docker compose -f docker-compose.yml -f deploy/server/docker-compose.server.yml exec api python -m app.modules.billing.cli create-superadmin you@example.com`
- Backups: add the cron line from `backup.sh`.

Update later: `cd /opt/stravica-social && git pull && bash deploy/server/deploy.sh`.
Roll back: `git checkout <previous commit> && bash deploy/server/deploy.sh`; restore data with
`pg_restore -U stravica -d stravica --clean` from `/var/backups/stravica-social`.

Ports 3110 / 8110 were free in the last server snapshot; `deploy.sh` stops if they are taken.
