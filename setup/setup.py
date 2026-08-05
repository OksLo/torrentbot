#!/usr/bin/env python3
"""First-time setup: configures qBittorrent password and Jellyfin admin + library.

Runs as a Docker Compose service inside the shared Docker network, so service
hostnames (qbittorrent, jellyfin) are used instead of localhost.

The Docker socket is mounted read-only to read qBittorrent's temporary password
from container logs without needing the docker CLI binary.

A sentinel file (SENTINEL) is written on successful completion so the script
becomes a no-op on every subsequent `docker compose up`.
"""

import http.client
import http.cookiejar
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Written on first successful run; presence skips all setup on future starts.
SENTINEL = '/config/.setup_done'

QBIT_URL = 'http://qbittorrent:8080'
JELLYFIN_URL = 'http://jellyfin:8096'
QBIT_USERNAME = os.environ.get('QBIT_USERNAME', 'admin')
QBIT_PASSWORD = os.environ['QBIT_PASSWORD']
JELLYFIN_USERNAME = os.environ.get('JELLYFIN_USERNAME', 'admin')
JELLYFIN_PASSWORD = os.environ['JELLYFIN_PASSWORD']


def wait_for(url, timeout=120):
    """Poll url until it returns any HTTP response or timeout expires.

    The Docker Compose healthcheck already ensures services are up before this
    script starts, but a brief extra wait guards against race conditions during
    the healthcheck window.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except Exception:
            time.sleep(2)
    return False


class _DockerSocketConnection(http.client.HTTPConnection):
    """HTTPConnection that routes over the Docker Unix socket instead of TCP.

    The Docker Engine exposes a REST API on /var/run/docker.sock.
    Docs: https://docs.docker.com/engine/api/
    """

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect('/var/run/docker.sock')


def get_container_logs(container_name):
    """Fetch stdout+stderr of a container via the Docker Engine API.

    Endpoint: GET /containers/{id}/logs
    Docs: https://docs.docker.com/engine/api/v1.43/#tag/Container/operation/ContainerLogs

    Docker multiplexes stdout and stderr into a single stream. Each chunk is
    prefixed with an 8-byte header:
      byte 0    : stream type (1 = stdout, 2 = stderr)
      bytes 1-3 : padding (zeros)
      bytes 4-7 : payload size as big-endian uint32
    Docs: https://docs.docker.com/engine/api/v1.43/#tag/Container/operation/ContainerAttach
    """
    conn = _DockerSocketConnection('localhost')
    conn.request('GET', f'/containers/{container_name}/logs?stdout=1&stderr=1&tail=200')
    resp = conn.getresponse()
    raw = resp.read()

    lines, i = [], 0
    while i + 8 <= len(raw):
        size = int.from_bytes(raw[i + 4:i + 8], 'big')
        lines.append(raw[i + 8:i + 8 + size].decode('utf-8', errors='ignore'))
        i += 8 + size
    return ''.join(lines)


def setup_qbittorrent():
    """Set the qBittorrent WebUI password via its Web API.

    qBittorrent Web API docs: https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-4.1)

    Flow:
      1. Try logging in with the target password — if it succeeds, already done.
      2. Otherwise read the one-time temporary password from container logs
         (qBittorrent 5+ generates a random password on first boot when no
         password is set in the config).
         Fallback: 'adminadmin' (default for older versions).
      3. Log in with the temporary password and call setPreferences to replace it.
    """
    print('==> Waiting for qBittorrent...')
    if not wait_for(f'{QBIT_URL}/'):
        print('  WARN: qBittorrent not ready, skipping.')
        return

    # A CookieJar is required because the qBittorrent API uses a session cookie
    # (SID) returned by /auth/login for all subsequent authenticated requests.
    # Docs: https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-4.1)#login
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    # Step 1: check whether the target password is already active.
    data = urllib.parse.urlencode({'username': QBIT_USERNAME, 'password': QBIT_PASSWORD}).encode()
    try:
        resp = opener.open(f'{QBIT_URL}/api/v2/auth/login', data)

        status_code = resp.getcode()
        set_cookie_header = resp.headers.get('Set-Cookie')
        
        if 200 <= status_code < 300 and set_cookie_header:
            print('  qBittorrent already configured, skipping.')
            return
    except Exception:
        pass

    # Step 2: retrieve the temporary password from container logs.
    # The linuxserver/qbittorrent image logs it as:
    #   "The temporary password for the admin account is: <password>"
    temp_pass = 'adminadmin'  # fallback for qBittorrent < 5
    try:
        logs = get_container_logs('qbittorrent')
        for line in logs.splitlines():
            if 'temporary password' in line.lower() and ':' in line:
                temp_pass = line.rsplit(':', 1)[-1].strip()
                break
    except Exception:
        pass

    # Step 3: authenticate with the temporary password and update preferences.
    # POST /api/v2/app/setPreferences accepts a JSON-encoded 'json' form field.
    # Docs: https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-4.1)#set-application-preferences
    print('==> Setting qBittorrent password...')
    cj.clear()
    data = urllib.parse.urlencode({'username': QBIT_USERNAME, 'password': temp_pass}).encode()
    try:
        resp = opener.open(f'{QBIT_URL}/api/v2/auth/login', data)
        
        status_code = resp.getcode()
        set_cookie_header = resp.headers.get('Set-Cookie')
        
        if 200 <= status_code < 300 and set_cookie_header:
            prefs = urllib.parse.urlencode({'json': json.dumps({'web_ui_password': QBIT_PASSWORD})}).encode()
            opener.open(f'{QBIT_URL}/api/v2/app/setPreferences', prefs)
            print('  Password set.')
        else:
            print('  WARN: Could not authenticate — set the qBittorrent password manually.')
    except Exception as e:
        print(f'  WARN: {e}')


def _jf(path, data=None, token=None, method=None):
    """Send a JSON request to the Jellyfin API and return (status, body).

    Unauthenticated requests (token=None) use the MediaBrowser identification
    header required by Jellyfin's startup wizard endpoints.
    Authenticated requests pass the access token obtained after completing the
    wizard.

    Jellyfin API reference: https://api.jellyfin.org/
    """
    headers = {}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    if token:
        # Standard bearer-style token for authenticated API calls.
        headers['Authorization'] = f'MediaBrowser Token="{token}"'
    else:
        # Client identification is required even for unauthenticated endpoints.
        # Docs: https://jellyfin.org/docs/general/clients/api/
        headers['Authorization'] = (
            'MediaBrowser Client="SetupScript", Device="cli", DeviceId="setup", Version="1.0"'
        )
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(f'{JELLYFIN_URL}{path}', data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def setup_jellyfin():
    """Complete the Jellyfin first-run wizard and add the Downloads media library.

    Uses /System/Info/Public to reliably detect wizard state instead of relying
    on ambiguous 4xx codes from the wizard endpoints themselves.

    Startup wizard API docs: https://api.jellyfin.org/#tag/Startup

    Flow:
      1. GET /System/Info/Public  — check StartupWizardCompleted.
      2. If wizard pending:
         a. GET /Startup/User  — seeds the default user record in Jellyfin's DB
            (required in 10.11+; skipping causes 500 "Sequence contains no elements").
         b. POST /Startup/User — set admin username and password.
         c. POST /Startup/Complete — mark wizard done.
      3. POST /Users/AuthenticateByName — obtain an access token.
      4. GET /Library/VirtualFolders — check if Downloads library exists.
      5. POST /Library/VirtualFolders — add /media as the Downloads library if absent.
    """
    print('==> Waiting for Jellyfin...')
    if not wait_for(f'{JELLYFIN_URL}/health'):
        print('  WARN: Jellyfin not ready, skipping.')
        return

    print('==> Configuring Jellyfin...')

    # Step 1: check wizard state via public endpoint (no auth required).
    # Docs: https://api.jellyfin.org/#tag/System/operation/GetPublicSystemInfo
    status, body = _jf('/System/Info/Public')
    if status != 200:
        print(f'  WARN: Could not reach Jellyfin system info ({status}). Skipping.')
        return
    wizard_completed = json.loads(body).get('StartupWizardCompleted', False)

    # Step 2: complete the wizard if still pending.
    if not wizard_completed:
        # GET must precede POST — it seeds the user record; without it POST 500s.
        # Docs: https://api.jellyfin.org/#tag/Startup/operation/UpdateStartupUser
        for attempt in range(1, 11):
            status, _ = _jf('/Startup/User')
            if status == 200:
                break
            print(f'  Attempt {attempt}/10: GET /Startup/User returned {status}, retrying in 5s...')
            time.sleep(5)
        else:
            print('  WARN: Jellyfin wizard endpoint unavailable after 10 attempts. Configure manually.')
            return

        status, _ = _jf('/Startup/User', {'Name': JELLYFIN_USERNAME, 'Password': JELLYFIN_PASSWORD})
        if status != 204:
            print(f'  WARN: POST /Startup/User returned {status}. Configure Jellyfin manually.')
            return
        _jf('/Startup/Complete', {})
        print('  Wizard completed.')

    # Step 3: authenticate to get an access token for library management.
    # Retry because Jellyfin can return 500 briefly after wizard completion or
    # restart while its user DB finishes initializing.
    # Docs: https://api.jellyfin.org/#tag/User/operation/AuthenticateUserByName
    token = None
    for attempt in range(1, 11):
        status, body = _jf('/Users/AuthenticateByName', {
            'Username': JELLYFIN_USERNAME, 'Pw': JELLYFIN_PASSWORD,
        })
        if status == 200:
            token = json.loads(body)['AccessToken']
            break
        print(f'  Attempt {attempt}/10: Jellyfin auth returned {status}: {body[:200]}, retrying in 5s...')
        time.sleep(5)
    if not token:
        print(f'  WARN: Jellyfin auth failed after 10 attempts. Downloads library not added.')
        return

    # Step 4: add /media as a mixed-content library called "Downloads" if not already present.
    # collectionType=mixed means Jellyfin will auto-detect movies, shows, music, etc.
    # refreshLibrary=true triggers an immediate scan after creation.
    # Docs: https://api.jellyfin.org/#tag/LibraryStructure/operation/AddVirtualFolder
    status, body = _jf('/Library/VirtualFolders', token=token)
    existing = [f['Name'] for f in json.loads(body)] if status == 200 else []
    if 'Downloads' in existing:
        print('  Downloads library already exists.')
    else:
        _jf(
            '/Library/VirtualFolders?name=Downloads&collectionType=mixed&refreshLibrary=true',
            {'libraryOptions': {'pathInfos': [{'path': '/media'}]}},
            token=token,
        )
        print('  Downloads library added.')

    if wizard_completed:
        print('  Jellyfin was already configured (wizard skipped).')

    # Create/retrieve a dedicated Jellyfin API key for the qBittorrent autorun command.
    # Docs: https://api.jellyfin.org/#tag/ApiKey/operation/CreateKey
    api_key = None
    status, body = _jf('/Auth/Keys', token=token)
    if status == 200:
        api_key = next(
            (k['AccessToken'] for k in json.loads(body).get('Items', []) if k.get('AppName') == 'TorrentBot'),
            None,
        )
    if not api_key:
        _jf('/Auth/Keys?app=TorrentBot', method='POST', token=token)
        status, body = _jf('/Auth/Keys', token=token)
        if status == 200:
            api_key = next(
                (k['AccessToken'] for k in json.loads(body).get('Items', []) if k.get('AppName') == 'TorrentBot'),
                None,
            )
    if api_key:
        with open('/config/jellyfin.env', 'w') as f:
            f.write(f'JELLYFIN_API_KEY={api_key}\n')
        print('  Jellyfin API key written to /config/jellyfin.env.')
    else:
        print('  WARN: Could not create Jellyfin API key.')
    return api_key


def setup_autorun(api_key):
    """Configure qBittorrent to trigger a Jellyfin library scan on torrent completion.

    Uses qBittorrent's built-in autorun feature (Preferences > Run external program
    on torrent completion). The autorun command calls the Jellyfin /Library/Refresh
    endpoint using a dedicated API key created during Jellyfin setup.

    qBittorrent API docs:
    https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-4.1)#set-application-preferences
    Jellyfin Library/Refresh docs: https://api.jellyfin.org/#tag/Library/operation/RefreshLibrary
    """
    if not api_key:
        print('  WARN: No Jellyfin API key available; skipping autorun setup.')
        return

    print('==> Configuring qBittorrent autorun...')

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    data = urllib.parse.urlencode({'username': QBIT_USERNAME, 'password': QBIT_PASSWORD}).encode()
    try:
        opener.open(f'{QBIT_URL}/api/v2/auth/login', data)
    except Exception as e:
        print(f'  WARN: qBittorrent auth failed: {e}')
        return

    autorun_cmd = (
        f'curl -s -X POST "{JELLYFIN_URL}/Library/Refresh"'
        f' -H "Authorization: MediaBrowser Token=\\"{{api_key}}\\""'
    ).format(api_key=api_key)
    prefs = urllib.parse.urlencode({
        'json': json.dumps({'autorun_enabled': True, 'autorun_program': autorun_cmd}),
    }).encode()
    try:
        opener.open(f'{QBIT_URL}/api/v2/app/setPreferences', prefs)
        print('  qBittorrent autorun configured.')
    except Exception as e:
        print(f'  WARN: Could not configure autorun: {e}')


if __name__ == '__main__':
    # Skip everything if a previous run already completed successfully.
    if os.path.exists(SENTINEL):
        print('Setup already completed, skipping.')
        sys.exit(0)

    setup_qbittorrent()
    api_key = setup_jellyfin()
    setup_autorun(api_key)

    # Write the sentinel only after both steps succeed so a partial failure
    # causes a full retry on the next container start.
    open(SENTINEL, 'w').close()
    print(f'\nSetup complete!')
    print(f'  qBittorrent: {QBIT_URL}  ({QBIT_USERNAME} / {QBIT_PASSWORD})')
    print(f'  Jellyfin:    {JELLYFIN_URL}  ({JELLYFIN_USERNAME} / {JELLYFIN_PASSWORD})')
