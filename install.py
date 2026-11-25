#!/bin/python3
"""
SRS Advert CRM — Opalstack installer (no secrets in this file).

Opalstack runs this as the app's OS user with env UUID, APPNAME, OPAL_TOKEN, API_URL.
App json (set when the app is created): db_name, db_user, app_command = public URL (https://...).

What it does:
  1. composer + deploy script into ~/apps/<app>/bin
  2. SSH deploy key (~/.ssh/srs_crm_deploy) — its PUBLIC half must be added to the private GitHub repo
  3. new random MariaDB password via API, written to env.production (chmod 600)
  4. one-time admin claim code -> Opalstack notice (only the account owner can read it)
  5. cron: deploy every 2 min (clones as soon as the deploy key is accepted), Laravel scheduler every minute
"""
import http.client
import json
import logging
import os
import secrets
import string
import subprocess
import sys
import urllib.request

RAW = 'https://raw.githubusercontent.com/syafwans-crypto/srs-crm-installer/main'
COMPOSER_URL = 'https://getcomposer.org/installer'
PHP = '/bin/php83'
API_HOST = os.environ.get('API_URL', 'https://my.opalstack.com').replace('https://', '').replace('http://', '').strip('/')
TOKEN = os.environ.get('OPAL_TOKEN', '')


def api(method, path, body=None):
    conn = http.client.HTTPSConnection(API_HOST, timeout=60)
    headers = {'Content-Type': 'application/json', 'Authorization': f'Token {TOKEN}'}
    conn.request(method, '/api/v1' + path, json.dumps(body) if body is not None else None, headers)
    r = conn.getresponse()
    data = r.read()
    try:
        return json.loads(data)
    except Exception:
        logging.warning('API %s %s -> %s %s', method, path, r.status, data[:200])
        return None


def run(cmd, cwd=None):
    logging.info('run: %s', cmd)
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True,
                       env={**os.environ, 'PATH': '/usr/local/bin:/usr/bin:/bin'})
    if r.returncode != 0:
        logging.warning('exit %s: %s', r.returncode, (r.stderr or r.stdout)[-500:])
    return r


def download(url, path, mode=0o700):
    with urllib.request.urlopen(url, timeout=120) as r, open(path, 'wb') as f:
        f.write(r.read())
    os.chmod(path, mode)


def write(path, content, mode=0o600):
    with open(path, 'w') as f:
        f.write(content)
    os.chmod(path, mode)


def gen(n=32):
    return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(n))


def site_url(app_uuid):
    """https URL of the first site routing to this app (if the site already exists)."""
    try:
        doms = {d['id']: d['name'] for d in (api('GET', '/domain/list/') or [])}
        for site in api('GET', '/site/list/') or []:
            if any(r.get('app') == app_uuid for r in site.get('routes', [])) and site.get('domains'):
                return 'https://' + doms.get(site['domains'][0], '')
    except Exception as e:
        logging.warning('site lookup: %s', e)
    return None


def main():
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(message)s')
    uuid = os.environ.get('UUID') or (sys.argv[sys.argv.index('-i') + 1] if '-i' in sys.argv else None)
    app = api('GET', f'/app/read/{uuid}')
    osuser = app['osuser_name']
    home = f'/home/{osuser}'
    appdir = f'{home}/apps/{app["name"]}'
    j = app.get('json') or {}
    app_url = (os.environ.get('SRS_APP_URL') or j.get('app_command') or site_url(uuid) or 'https://syafwan.opalstacked.com').rstrip('/')
    db_name = j.get('db_name') or 'srscrm'
    db_user = j.get('db_user') or 'srscrm'
    logging.info('installing SRS Advert CRM into %s (%s)', appdir, app_url)

    for d in ('bin', 'logs', 'current/public', '.composer'):
        os.makedirs(f'{appdir}/{d}', exist_ok=True)

    # 1. tools
    download(COMPOSER_URL, f'{appdir}/bin/composer-setup.php', 0o600)
    run(f'{PHP} {appdir}/bin/composer-setup.php --install-dir={appdir}/bin --filename=composer')
    download(f'{RAW}/deploy.sh', f'{appdir}/bin/deploy.sh', 0o700)

    # 2. deploy key
    os.makedirs(f'{home}/.ssh', mode=0o700, exist_ok=True)
    key = f'{home}/.ssh/srs_crm_deploy'
    if not os.path.exists(key):
        run(f'ssh-keygen -t ed25519 -N "" -C srs-crm-deploy@{osuser} -f {key}')
    pub = open(key + '.pub').read().strip()

    # 3. database password (random, never leaves the server)
    db_pass = gen(32)
    users = api('GET', '/mariauser/list/') or []
    mu = next((u for u in users if u.get('name') == db_user), None)
    if mu:
        api('POST', '/mariauser/update/', [{'id': mu['id'], 'password': db_pass}])
    else:
        logging.warning('MariaDB user %s not found', db_user)

    # 4. environment
    claim = gen(24)
    write(f'{appdir}/env.production', '\n'.join([
        'APP_NAME="SRS Advert CRM"', 'APP_ENV=production', 'APP_KEY=', 'APP_DEBUG=false', f'APP_URL={app_url}',
        'APP_LOCALE=ms', 'APP_FALLBACK_LOCALE=en', 'APP_TIMEZONE=UTC',
        'LOG_CHANNEL=daily', 'LOG_LEVEL=warning',
        'DB_CONNECTION=mysql', 'DB_HOST=localhost', 'DB_PORT=3306', f'DB_DATABASE={db_name}', f'DB_USERNAME={db_user}', f'DB_PASSWORD={db_pass}',
        'SESSION_DRIVER=database', 'SESSION_LIFETIME=10080', 'SESSION_SECURE_COOKIE=true',
        'CACHE_STORE=database', 'QUEUE_CONNECTION=sync', 'MAIL_MAILER=log',
        f'ADMIN_CLAIM_CODE={claim}', '',
    ]))

    # placeholder page until the first deploy replaces current/
    write(f'{appdir}/current/public/index.html',
          '<!doctype html><meta charset=utf-8><title>SRS Advert CRM</title>'
          '<body style="font-family:sans-serif;padding:40px;background:#0B1B3F;color:#fff">'
          '<h1>SRS Advert CRM sedang dipasang</h1><p>Menunggu deploy key GitHub.</p>'
          f'<pre id="deploy-key" style="white-space:pre-wrap;background:#fff1;padding:12px">{pub}</pre></body>', 0o644)

    # 5. cron
    cur = run('crontab -l')
    cron = cur.stdout if cur.returncode == 0 else ''
    lines = [l for l in cron.splitlines() if 'srs-crm' not in l]
    lines.append(f'*/2 * * * * SRS_APP_DIR={appdir} bash {appdir}/bin/deploy.sh >> {appdir}/logs/deploy.log 2>&1 # srs-crm deploy')
    lines.append(f'* * * * * cd {appdir}/current && [ -f artisan ] && {PHP} artisan schedule:run >> /dev/null 2>&1 # srs-crm scheduler')
    write(f'{appdir}/.crontab', '\n'.join(lines) + '\n', 0o600)
    run(f'crontab {appdir}/.crontab')

    # 6. tell the owner (Notice Log): claim link
    api('POST', '/notice/create/', [{'type': 'M', 'content':
        f'SRS Advert CRM dipasang. Cipta akaun admin di: {app_url}/claim?code={claim} (sekali sahaja).'}])

    api('POST', '/app/installed/', [{'id': uuid}])
    run(f'SRS_APP_DIR={appdir} bash {appdir}/bin/deploy.sh >> {appdir}/logs/deploy.log 2>&1')
    logging.info('done')


if __name__ == '__main__':
    main()
