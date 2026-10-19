# Deployment

This page takes you from the demo to a server that your family uses every day. It shows how to keep the server running, how to keep it private, and how to reach it from a phone.

Every way to run it starts the same program, `alexia-api serve`, with the same configuration file. Pick the way that fits the machine you have.

| Way | Choose it when | Start here |
| --- | --- | --- |
| Docker Compose | You have a home server, a NAS, or a small VPS with Docker. This is the easiest way to keep the server running. | [Docker Compose](#docker-compose) |
| `docker run` | A tool such as Portainer or Unraid starts your containers, or you do not want Compose. | [Docker without Compose](#docker-without-compose) |
| A service without Docker | You prefer to run the program directly on a Linux machine. | [A service without Docker](#a-service-without-docker) |
| Kubernetes | You already run a cluster. | [Kubernetes](#kubernetes) |

## What every setup needs

- One configuration file, `alexia-api.toml`, with an `[accounts.NAME]` block for each portal login. The [configuration guide](configuration.md) explains each setting.
- Your portal user name and password, kept outside that file. The file names an environment variable with `env:NAME`, or a file with `file:/path`.
- A folder that survives a restart. The server keeps its few files there, which are the hashes of your API keys and the pause file of each account. The setting is `state_dir`.
- One server process for each set of accounts. The pause between requests and the lock on each account live inside the process, so two processes on one account would each send their own requests and lose the gentle pace.

If you have not run the demo yet, [getting started](getting-started.md) shows how.

## Docker Compose

The repository holds a [`compose.yaml`](../compose.yaml) that builds the image and runs it with care. The container runs as an ordinary user, its root file system is read-only, it has no extra Linux capabilities, and its port opens on your own machine only. Compose 2.24 or newer reads the file. Check your version with `docker compose version`.

### Set it up

1. Get the project and open its folder.

   ```bash
   git clone https://github.com/GlitchInstitute/alexia-familia-api.git
   cd alexia-familia-api
   ```

2. Copy the two starter files. Git ignores both, so your login never lands in a commit.

   ```bash
   cp alexia-api.example.toml alexia-api.toml
   cp .env.example .env
   ```

3. Open `alexia-api.toml` and paste the address of your school's login page into `login_url`. The account is called `family`. If you rename it, rename the two variables in `.env` the same way, because the settings refer to them as `env:PORTAL_FAMILY_USERNAME` and `env:PORTAL_FAMILY_PASSWORD`.

4. Open `.env` and write your portal user name and password between the single quotes. Read [Passwords with special characters](#passwords-with-special-characters) if yours has a `$`, a `#`, or a quote.

5. Build the image and start the server.

   ```bash
   docker compose up -d --build
   ```

6. Make a key and check the setup. The key appears once, so copy it.

   ```bash
   docker compose exec alexia-api alexia-api keys create phone
   docker compose exec alexia-api alexia-api doctor
   ```

7. Ask for your children.

   ```bash
   curl -H "Authorization: Bearer YOUR_KEY" http://127.0.0.1:8000/v1/accounts/family/children
   ```

The first request makes the server sign in to the portal, so it takes a moment. `docker compose logs -f alexia-api` shows what the server does.

### What the Compose file does

| Line | Effect |
| --- | --- |
| `ports: "127.0.0.1:8000:8000"` | Only this machine can reach the server. [Put a proxy in front](#put-a-proxy-with-https-in-front) to share it. |
| `volumes: data:/data` | Keeps the API keys and the account pause files when Compose replaces the container. |
| The `alexia-api.toml` bind mount | Gives the server your settings, read-only. Compose stops with an error when the file is missing, and it does not make an empty folder in its place. |
| `env_file: .env` | Passes your portal login to the container. The file may be missing, and then `doctor` names the variables that are not set. |
| `read_only`, `tmpfs: /tmp`, `cap_drop: ALL`, `no-new-privileges` | Limit what the process can do if something goes wrong. |
| `restart: unless-stopped` | Starts the server again after a crash or a reboot. |

### Passwords with special characters

Compose reads `.env` with rules of its own, and a `$` in an unquoted value starts a variable. The password `pa$word` would reach the school as `pa`, and a wrong password can lock your account. For that reason `.env.example` puts each value in single quotes, where no character is special.

- Write the value between single quotes, as in `PORTAL_FAMILY_PASSWORD='pa$word # 1'`. A `$` and a `#` are then ordinary characters.
- A password that contains a single quote goes between double quotes. Write `\$` for a dollar sign, `\"` for a double quote, and `\\` for a backslash.
- Check what the container received before the first login. This prints the length of the password and never the password itself. The number must match the length of yours.

  ```bash
  docker compose exec alexia-api python -c "import os; print(len(os.environ['PORTAL_FAMILY_PASSWORD']))"
  ```

`docker run --env-file` reads a file differently. It keeps quotes as part of the value, so do not reuse this file there. The [next section](#docker-without-compose) shows the form it wants.

### Change the port

Change only the first number in `ports`. The line `"127.0.0.1:9000:8000"` opens port 9000 on your machine and leaves port 8000 inside the container, where the health check looks for it.

Leave the address `127.0.0.1` in place. A line such as `"9000:8000"` opens the port on every network card, and Docker does that around host firewalls such as `ufw`.

### Keep the data

The volume `data` holds `state/api-keys.json`, which has the hashes of your keys, and `state/breaker/`, which has the pause file of each account. The files hold no school data.

- `docker compose down` removes the container and keeps the volume.
- `docker compose down --volumes` removes the volume too. You then make your keys again and update the apps that use them.

### Update

```bash
git pull
docker compose up -d --build
```

Read the [changelog](../CHANGELOG.md) first. Compose replaces the container, and the keys stay in the volume.

## Docker without Compose

Build the image, put your login in a file, and run the image with the same limits that the Compose file sets.

```bash
docker build --tag alexia-familia-api .
```

Make a file called `.env.docker` with one `NAME=value` line for each secret. Write no quotes, because `docker run` keeps them as part of the value. Git ignores every file whose name starts with `.env`.

```text
PORTAL_FAMILY_USERNAME=your user name
PORTAL_FAMILY_PASSWORD=your password
```

Start the container.

```bash
docker run --detach --name alexia-api --restart unless-stopped \
  --publish 127.0.0.1:8000:8000 \
  --mount type=volume,source=alexia-data,target=/data \
  --mount type=bind,source="$PWD/alexia-api.toml",target=/data/alexia-api.toml,readonly \
  --env-file .env.docker \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  alexia-familia-api
```

Use `--mount` for the settings file. The short `--volume` form makes an empty folder named `alexia-api.toml` when the file is missing, and the server then cannot read its settings. Make a key and check the setup the same way as with Compose.

```bash
docker exec alexia-api alexia-api keys create phone
docker exec alexia-api alexia-api doctor
```

## A service without Docker

This setup runs the program as a systemd service on Linux. The code stays read-only for the service, and the service user can write only to its own state folder.

1. Install [pixi](https://pixi.sh), then install the project in `/opt`.

   ```bash
   sudo install --directory --owner "$USER" /opt/alexia-familia-api
   git clone https://github.com/GlitchInstitute/alexia-familia-api.git /opt/alexia-familia-api
   cd /opt/alexia-familia-api
   pixi install --locked
   ```

2. Make a user for the service and a folder for its settings.

   ```bash
   sudo useradd --system --home-dir /var/lib/alexia-api --shell /usr/sbin/nologin alexia
   sudo install --directory --owner root --group alexia --mode 0750 /etc/alexia-api
   ```

3. Copy the starter settings and paste the address of your school's login page into `login_url`.

   ```bash
   sudo cp alexia-api.example.toml /etc/alexia-api/alexia-api.toml
   sudoedit /etc/alexia-api/alexia-api.toml
   ```

4. Keep the portal login in two files, so that the settings hold no secret. Change the `username` and `password` lines of the account to name them.

   ```toml
   username = "file:/etc/alexia-api/family-username"
   password = "file:/etc/alexia-api/family-password"
   ```

   Write your user name in the first file and your password in the second. The server removes the line ending at the end of the file and nothing else, so an editor's final newline is fine.

   ```bash
   sudoedit /etc/alexia-api/family-username
   sudoedit /etc/alexia-api/family-password
   sudo chown root:alexia /etc/alexia-api/alexia-api.toml /etc/alexia-api/family-username /etc/alexia-api/family-password
   sudo chmod 0640 /etc/alexia-api/alexia-api.toml /etc/alexia-api/family-username /etc/alexia-api/family-password
   ```

5. Write the unit to `/etc/systemd/system/alexia-api.service`.

   ```ini
   [Unit]
   Description=alexia-familia-api, a REST API for the Alexia Familia parent portal
   After=network-online.target
   Wants=network-online.target

   [Service]
   User=alexia
   Group=alexia
   Environment=ALEXIA_API_CONFIG=/etc/alexia-api/alexia-api.toml
   Environment=ALEXIA_API_STATE_DIR=/var/lib/alexia-api
   ExecStart=/opt/alexia-familia-api/.pixi/envs/default/bin/alexia-api serve
   StateDirectory=alexia-api
   StateDirectoryMode=0700
   Restart=on-failure
   RestartSec=5
   UMask=0077
   NoNewPrivileges=yes
   CapabilityBoundingSet=
   ProtectSystem=strict
   ProtectHome=yes
   PrivateTmp=yes
   PrivateDevices=yes
   ProtectKernelTunables=yes
   ProtectKernelModules=yes
   ProtectControlGroups=yes
   RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

   [Install]
   WantedBy=multi-user.target
   ```

6. Start the service and make a key. The `keys` command must run as the service user with the same two variables, so that it writes where the server reads.

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now alexia-api
   sudo --user=alexia ALEXIA_API_CONFIG=/etc/alexia-api/alexia-api.toml ALEXIA_API_STATE_DIR=/var/lib/alexia-api \
     /opt/alexia-familia-api/.pixi/envs/default/bin/alexia-api keys create phone
   ```

`journalctl --unit alexia-api --follow` shows the log. To update, run `git pull` and `pixi install --locked` in `/opt/alexia-familia-api`, then `sudo systemctl restart alexia-api`.

## Kubernetes

A cluster can run the image that the Dockerfile builds. Push it to a registry that your cluster reads. The table lists what the server needs from a pod. It comes from the way the image works, and nobody has tried it on a cluster yet, so test it before you rely on it.

| Need | How |
| --- | --- |
| The image's user | `runAsUser: 10001`, `runAsGroup: 10001`, and `runAsNonRoot: true`. |
| A folder that survives | A persistent volume claim at `/data`, and `fsGroup: 10001` so that the user can write to it. |
| One process | `replicas: 1` and `strategy: type: Recreate`. A rolling update would run two servers on one account for a moment. |
| Settings | A ConfigMap mounted at `/etc/alexia`, with the variables `ALEXIA_API_CONFIG=/etc/alexia/alexia-api.toml` and `ALEXIA_API_STATE_DIR=/data/state`. |
| Secrets | A Secret whose keys the settings name after `env:`, passed with `secretKeyRef`. Or a Secret mounted as files that the settings name after `file:`. |
| A read-only root | `readOnlyRootFilesystem: true` and an `emptyDir` volume at `/tmp`. |
| Probes | `/healthz` for liveness and `/readyz` for readiness, both on port 8000. |
| Keys | `kubectl exec deploy/alexia-api -- alexia-api keys create phone`. |

The pod stays not ready until it holds one key, because `/readyz` asks for one. `kubectl exec` works on a pod that is not ready, so make the first key that way. Neither probe depends on `allowed_hosts`, so a probe that uses the pod's address works. A Kubernetes service named `alexia-api` adds variables that start with `ALEXIA_API_`, and the server ignores those.

## Share the server safely

The server listens on `127.0.0.1` by default, and no other machine can reach it. Keep it that way until you need more. Each step below adds some risk, so add only what you use.

### Reach it from your own devices

A private network is the safest way to reach the server from a phone that is away from home. A tool such as Tailscale or WireGuard puts your devices on a network that the internet cannot see. A key travels in every request, so use `https` there as well when you can.

Some calendar services fetch the calendar from their own servers, and Google Calendar is one of them. They need an address that works from the internet. The [calendar guide](calendars.md) says what each kind of app needs.

### Put a proxy with https in front

A reverse proxy takes the connection from the internet, adds `https`, compresses the answers, and passes each request on to the server on `127.0.0.1`. The server does not compress. In the demo, the calendar file for a family is 285 KB, and the agenda of one child for 90 days is 114 KB. With the examples below they shrink to between 14 KB and 18 KB, and between 6 KB and 8 KB.

Give the server its own host name, such as `alexia.example.test`. The server has no setting for a path prefix such as `/alexia`.

#### Caddy

Caddy gets and renews a certificate for a public host name by itself. Ports 80 and 443 must reach it. The `encode` line turns on `zstd` and `gzip`.

```caddy
alexia.example.test {
	encode
	reverse_proxy 127.0.0.1:8000
}
```

#### nginx

Get a certificate first, for example with certbot, and point the two certificate lines at it. The `Host` line matters. Without it nginx sends the address of the server as the host name, and `allowed_hosts` refuses the request. The timeout line matters too, as [the timeouts below](#timeouts) explain.

```nginx
server {
    listen 443 ssl;
    server_name alexia.example.test;

    ssl_certificate     /etc/ssl/alexia/fullchain.pem;
    ssl_certificate_key /etc/ssl/alexia/privkey.pem;

    gzip on;
    gzip_types application/json text/calendar;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

### Tighten the settings

Once the server is reachable, set these two lines in `alexia-api.toml` with your own host name.

```toml
allowed_hosts = ["alexia.example.test"]
docs_enabled = false
```

`allowed_hosts` makes the server answer only for the names you list, and the two health checks still answer for any name. `docs_enabled = false` turns off `/docs`, `/redoc`, and `/openapi.json`, because the `/docs` page loads scripts from a public CDN in the browser. Set `cors_origins` only when a web page that you run calls the API from a browser. Give each app its own key with the fewest scopes that work, and give calendar apps keys that hold only `feed`. Run `doctor` again afterward, and read [SECURITY.md](../SECURITY.md).

### A proxy on another machine or in a container

The server trusts the `X-Forwarded-Proto` and `X-Forwarded-For` headers only from `127.0.0.1`. A proxy in another container or on another machine has another address, so the server ignores its headers. A redirect then points to `http` instead of `https`. Set the variable `FORWARDED_ALLOW_IPS` for the server to the address of the proxy.

Use `*` only when nothing but the proxy can reach the server's port. A Compose project that runs the proxy and the server together and publishes no port for the server is such a case.

```yaml
services:
  alexia-api:
    environment:
      FORWARDED_ALLOW_IPS: "*"
```

### Timeouts

Let the proxy wait at least 120 seconds for an answer. After a quiet time the server signs in to the portal and reads several pages one after the other, and a large mailbox needs many pages. Caddy waits without a limit unless you set one. nginx stops waiting after 60 seconds, which is why the nginx example sets `proxy_read_timeout 120s`.

## Watch the server

### Health checks

- `/healthz` answers `200` whenever the process runs. Use it to decide that the process is alive.
- `/readyz` answers `200` when the server has at least one account and one key, can read its key file, and can write its state folder. Otherwise it answers `503` and names the failed checks. Use it to decide that the server can serve requests.

Neither check calls the portal, and both answer for any host name. The image's own health check uses `/healthz` only, so a portal that is down never makes the container unhealthy.

### Logs

The server writes one line for each request to standard error, where Docker, systemd, and Kubernetes collect it. A failed request carries the `code` of its problem, which is the quickest way to see why it failed. This is a run that has no portal behind it, so the request for the children fails with `transport`.

```text
2026-10-19T03:31:04Z INFO    alexia_api.access GET /healthz 200 3ms request_id=8d00bd2f24b54a458cdd8ac4fff892d3
2026-10-19T03:31:04Z INFO    alexia_api.access GET /v1/accounts/{account} 200 18ms request_id=17cb231f063e4e2094f683ebaee60e89 account=marta key=phone
2026-10-19T03:31:04Z INFO    alexia_api.access GET /v1/accounts/{account} 404 1ms request_id=b0147bc51ce24e838fa6db7098cb5109 key=phone code=account_not_found
2026-10-19T03:31:04Z INFO    alexia_api.access GET /v1/accounts/{account}/children 502 12ms request_id=94748045aef24c6ba5a7352880a17f4b account=marta key=phone code=transport
2026-10-19T03:31:04Z INFO    alexia_api.access GET /v1/accounts 401 1ms request_id=a358e8f45ab547c4afd3746630a2b0c7 code=missing_api_key
```

Set `log_format = "json"` for one object per line, which log tools read without help.

```jsonl
{"time": "2026-10-19T03:31:29Z", "level": "INFO", "logger": "alexia_api.access", "message": "GET /v1/accounts/{account}/children 502 25ms", "request_id": "be0b8ed62db24f4287451a616a42eb59", "account": "marta", "key": "phone", "code": "transport"}
```

The line names the route and not the address, so a child's name in a URL never reaches the log. An account name appears only for an account that you configured. A client that reports a problem quotes its `request_id`, and the line with that id has the `code`. The [errors page](errors.md) explains each code.

### Memory and traffic

In a test with the demo, the container used about 70 MiB of memory. A file that a client downloads is held in memory while it travels, up to `max_attachment_mib` for each download in progress, which is 25 by default. An idle server sends nothing to the portal, because it has no background work.

## What has been tested

- The Compose setup, the `docker run` command, the quoting rules for single and double quotes, and the replacement of a container were run on Docker with Compose 5.6. The keys survived the replacement, and a password with a `$`, a `#`, and a quote reached the container unchanged.
- The Caddy 2 and nginx 1 examples pass their own syntax checks as written. They ran in front of the demo with `https`, and the compression sizes above come from those runs. A redirect kept `https` only when `FORWARDED_ALLOW_IPS` named the proxy. With `allowed_hosts` set, nginx got the `invalid_host` problem without the `Host` line and an answer with it.
- The systemd unit passes `systemd-analyze verify` on systemd 255. Nobody has run it as a service, and nobody has run the Kubernetes table on a cluster. Treat both as a starting point.

## Before you share the server

- The port is open on `127.0.0.1` only, or a firewall blocks it.
- A proxy gives `https`.
- `allowed_hosts` lists your host names, and `docs_enabled` is `false`.
- Each app has its own key with the fewest scopes that work.
- `doctor` shows no `warn` or `fail` line that you do not understand.
