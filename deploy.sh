#!/bin/bash
# SRS Advert CRM — auto deploy on Opalstack. Run by cron every 2 minutes (installed by srs-crm-installer).
# Pulls origin/main; on change: composer install, migrate, cache. First run: clones into place.
set -u
APP="${SRS_APP_DIR:?}"
PHP=/bin/php83
REPO=git@github.com:syafwans-crypto/srs-advert-crm.git
export HOME="${HOME:-$(dirname "$(dirname "$APP")")}"
export PATH="$APP/bin:/usr/local/bin:/usr/bin:/bin"
export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/srs_crm_deploy -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
export COMPOSER_HOME="$APP/.composer"

exec 9>"$APP/.deploy.lock"
flock -n 9 || exit 0
log() { echo "[$(date '+%F %T')] $*"; }

FIRST=0
if [ ! -d "$APP/current/.git" ]; then
  rm -rf "$APP/release-tmp"
  if ! git clone -q --depth 30 "$REPO" "$APP/release-tmp" 2>"$APP/logs/clone.err"; then
    echo "waiting-for-deploy-key" > "$APP/status.txt"
    exit 0
  fi
  rm -rf "$APP/current"
  mv "$APP/release-tmp" "$APP/current"
  FIRST=1
  log "cloned"
fi

cd "$APP/current" || exit 1
git fetch -q --depth 30 origin main || { log "fetch failed"; exit 1; }
if [ "$FIRST" = 0 ] && [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && [ -f "$APP/.deployed" ]; then
  exit 0
fi
git reset -q --hard origin/main
log "deploying $(git rev-parse --short HEAD)"

[ -f .env ] || cp "$APP/env.production" .env
mkdir -p storage/framework/{cache,sessions,views} storage/logs bootstrap/cache
$PHP "$APP/bin/composer" install --no-dev --no-interaction --no-progress --optimize-autoloader \
  --ignore-platform-req=ext-gmp --ignore-platform-req=ext-bcmath 2>&1 | tail -3
grep -q '^APP_KEY=base64' .env || $PHP artisan key:generate --force
$PHP artisan migrate --force
$PHP artisan crm:bootstrap
$PHP artisan optimize:clear >/dev/null
$PHP artisan config:cache && $PHP artisan route:cache && $PHP artisan view:cache
git rev-parse HEAD > "$APP/.deployed"
echo "live $(git rev-parse --short HEAD) $(date '+%F %T')" > "$APP/status.txt"
log "done"
