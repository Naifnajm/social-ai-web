# Deploying to social.stravica.nl (server with nginx already on 80/443)

The stock `docker-compose.yml` ships Caddy on ports 80/443. This server already runs nginx there, so the override in
this folder turns Caddy off and publishes the web app and the API on loopback only; nginx proxies to them and certbot
issues the certificate.

1. **DNS** (GoDaddy → stravica.nl → DNS): add `A` record, name `social`, value `51.75.27.21`, TTL 600.
   Check: `dig +short social.stravica.nl` must print `51.75.27.21`.
2. **Code** on the server:
   ```bash
   git clone git@github.com:Naifnajm/social-ai-web.git /opt/stravica-social
   cd /opt/stravica-social && bash deploy/server/deploy.sh
   ```
   The script creates `.env` with random secrets (mode 600), builds, starts, waits for health and backs up the
   database first on every later run.
3. **nginx + certificate**:
   ```bash
   cp deploy/server/nginx-social.stravica.nl.conf /etc/nginx/sites-available/social.stravica.nl
   ln -s /etc/nginx/sites-available/social.stravica.nl /etc/nginx/sites-enabled/
   nginx -t && systemctl reload nginx
   certbot --nginx -d social.stravica.nl --redirect
   ```
4. **Platform admin**: `docker compose -f docker-compose.yml -f deploy/server/docker-compose.server.yml exec api python -m app.modules.billing.cli create-superadmin you@example.com`
5. **Backups**: add the cron line from `backup.sh`.

Update later: `cd /opt/stravica-social && git pull && bash deploy/server/deploy.sh`.
Roll back: `git checkout <previous commit> && bash deploy/server/deploy.sh`; restore data with
`pg_restore -U stravica -d stravica --clean` from `/var/backups/stravica-social`.

Ports 3110 / 8110 were free in the last server snapshot; `deploy.sh` stops if they are taken.
