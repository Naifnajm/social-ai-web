#!/usr/bin/env bash
# First install and every update of Stravica Social on the server.
# Run on the server, from the repository root:   bash deploy/server/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
# Domain: first argument, else the one already in .env, else the temporary nip.io name (needs no DNS record).
#   bash deploy/server/deploy.sh                       # temporary: social.51.75.27.21.nip.io
#   bash deploy/server/deploy.sh social.stravica.nl    # later: switch to the real subdomain
DOMAIN="${1:-$(grep -s '^SAI_DOMAIN=' .env | cut -d= -f2)}"
DOMAIN="${DOMAIN:-social.51.75.27.21.nip.io}"
COMPOSE=(docker compose -f docker-compose.yml -f deploy/server/docker-compose.server.yml)
BACKUPS=/var/backups/stravica-social

if [ ! -f .env ]; then
  umask 077
  cp .env.example .env
  sed -i "s|^SAI_DOMAIN=.*|SAI_DOMAIN=${DOMAIN}|" .env
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|" .env
  sed -i "s|^SAI_SECRET_KEY=.*|SAI_SECRET_KEY=$(openssl rand -hex 48)|" .env
  echo "Created .env with new random secrets (mode 600). Add SMTP, social apps and Stripe keys there later."
fi
chmod 600 .env
sed -i "s|^SAI_DOMAIN=.*|SAI_DOMAIN=${DOMAIN}|" .env      # a new domain only changes this line; secrets stay

for port in 3110 8110; do
  if ss -ltn "sport = :$port" | grep -q LISTEN && ! "${COMPOSE[@]}" ps -q 2>/dev/null | grep -q .; then
    echo "Port $port is already in use by something else. Change it in deploy/server/ and retry." >&2; exit 1
  fi
done

# Back up the database before touching a running install.
if "${COMPOSE[@]}" ps -q db 2>/dev/null | grep -q .; then
  mkdir -p "$BACKUPS"; chmod 700 "$BACKUPS"
  "${COMPOSE[@]}" exec -T db pg_dump -U stravica -Fc stravica > "$BACKUPS/pre-deploy_$(date +%F_%H%M).dump"
  echo "Database backed up to $BACKUPS"
fi

"${COMPOSE[@]}" build
"${COMPOSE[@]}" up -d --remove-orphans      # the API container runs the migrations on start

echo -n "Waiting for the API"
for _ in $(seq 1 60); do
  if curl -fs http://127.0.0.1:8110/api/health >/dev/null; then echo " ok"; break; fi
  echo -n "."; sleep 2
done
curl -fs http://127.0.0.1:8110/api/health >/dev/null || { echo; "${COMPOSE[@]}" logs --tail 50 api; exit 1; }
curl -fs -o /dev/null http://127.0.0.1:3110/ar/welcome || { "${COMPOSE[@]}" logs --tail 50 web; exit 1; }
"${COMPOSE[@]}" ps
echo "Up on 127.0.0.1:3110 (web) and 127.0.0.1:8110 (api)."

# nginx site + certificate for the domain (other sites are not touched; nginx is only reloaded after nginx -t).
SITE=/etc/nginx/sites-available/stravica-social
[ -f "$SITE" ] && cp -p "$SITE" "$SITE.bak.$(date +%F_%H%M)"
sed "s|server_name .*;|server_name ${DOMAIN};|" deploy/server/nginx-social.stravica.nl.conf > "$SITE"
ln -sfn "$SITE" /etc/nginx/sites-enabled/stravica-social
nginx -t
systemctl reload nginx
if getent hosts "$DOMAIN" | grep -q .; then
  certbot --nginx -d "$DOMAIN" --redirect --non-interactive --agree-tos --register-unsafely-without-email \
    || echo "Certificate not issued yet (DNS not pointing here?). Re-run this script when the record is live."
else
  echo "$DOMAIN does not resolve yet: add the DNS record, then re-run this script for the certificate."
fi
echo "Open: https://${DOMAIN}/"
