# Configuration

You can set everything in a file, in environment variables, or in both. A variable wins over the file, and a setting that you leave out keeps its default. This page explains how the server finds and reads its settings. The [settings reference](settings.md) lists every setting with its default.

## Where a setting comes from

The server looks in three places and takes the first one that names the setting.

| Order | Place | When to use it |
| --- | --- | --- |
| 1 | An environment variable such as `ALEXIA_API_TIMEZONE` | Containers, and any value that differs between machines. |
| 2 | The configuration file, `alexia-api.toml` | Everything you want to keep and read later. |
| 3 | The default | Most settings. |

The file and the variables have the same names. `rate_limit_per_minute` in the file is `ALEXIA_API_RATE_LIMIT_PER_MINUTE` in the environment.

## Find the file

A command looks for the file in this order.

1. The path after `-c` or `--config`.
2. The path in the `ALEXIA_API_CONFIG` variable.
3. A file named `alexia-api.toml` in the folder where you run the command.

When none of these exists, the server runs on variables and defaults alone. A path that you name in step 1 or step 2 has to exist, or the command stops and names it.

The commands `serve`, `doctor`, `keys`, and `accounts` read the configuration. The `init` command writes it. The `demo` and `openapi` commands read nothing, so a stray variable can never put a real account into the demo.

Write a starter file with the `init` command. It adds every setting as a comment with its default and a short explanation, and it holds no password.

```bash
pixi run init --account marta --login-url "https://portal.example.test/ACWeb/LogOn.aspx?key=your-school-key"
```

Use `--print` to see the file without writing it, and `--force` to replace a file that exists.

## Environment variables

A variable name is `ALEXIA_API_`, then the name of the setting in capital letters. A setting inside a table, such as `tracking` in the `cache` table, takes two underscores between the table and the setting.

```bash
export ALEXIA_API_TIMEZONE="Europe/Madrid"
export ALEXIA_API_CACHE__TRACKING=60
export ALEXIA_API_ALLOWED_HOSTS="api.example.test,*.example.test"
```

- A true or false value is written `true` or `false`.
- A list is written as names separated by commas. A list that starts with `[` is read as JSON.
- An account is a table, so its variables read `ALEXIA_API_ACCOUNTS__MARTA__LOGIN_URL`. The account name in the variable is lower case in the server, so this account is `marta`. A name with a hyphen cannot be written as a variable, so use the file for it.
- A pin for a child reads `ALEXIA_API_ACCOUNTS__MARTA__SLUGS__LUCIA`, and its value is the student id.

The server stops at a variable that starts with `ALEXIA_API_` and names no setting. The message names the variable and suggests the closest setting, as in `ALEXIA_API_RATE_LIMIT names no setting, did you mean ALEXIA_API_RATE_LIMIT_PER_MINUTE?`. A typo in a safety setting must never fall back to its default without a word. An unknown name in the file stops the server too.

Docker and Kubernetes add variables that start with the project's name when a service has it, such as `ALEXIA_API_SERVICE_HOST` and `ALEXIA_API_PORT_8000_TCP`. The server ignores those.

The server does not read `.env` files. Docker Compose reads one and passes the values on as variables.

## Keep passwords out of the file

The `username` and `password` of an account take one of three forms.

| Form | Meaning |
| --- | --- |
| `env:NAME` | Read the value from the environment variable `NAME`. |
| `file:/path` | Read the value from a file. Only the line ending is removed, because a password can start or end with a space. A path may start with `~`. |
| Anything else | The text is the value itself. Avoid this, because the file then holds a secret. |

```toml
[accounts.marta]
login_url = "https://portal.example.test/ACWeb/LogOn.aspx?key=your-school-key"
username = "env:PORTAL_MARTA_USERNAME"
password = "file:/run/secrets/portal_marta_password"
```

Some rules help you avoid a stuck server.

- Write the prefix in lower case, exactly `env:` or `file:`.
- Do not start the name of a secret variable with `ALEXIA_API_`. The server treats every variable with that start as a setting, so `ALEXIA_API_MARTA_PASSWORD` stops the server. Use a name like `PORTAL_MARTA_PASSWORD`.
- The server reads all secrets when it starts. When one is missing, one message lists every secret that cannot be read, and the server does not start.
- An empty secret is an error.
- Error messages name the setting and the variable or file, and they never show a value.

The `doctor` command warns when a password sits in the file as plain text.

## Accounts

An account is one portal login, which means one guardian at one school. A server holds one or more accounts, and each has a short name that goes into URLs, as in `/v1/accounts/marta/children`.

- A name uses lower case letters, digits, and hyphens, and it is at most 40 characters long.
- Each account has its own session, its own cache, and its own pause on logins, so a wrong password on one account never stops another.
- One login that sees several children needs one account. Siblings are not separate accounts.
- Two parents who each have a login can both be accounts, under two names. Use two accounts as well when two schools are involved.

There are two ways to say where the portal is.

| Way | Settings | When to use it |
| --- | --- | --- |
| Paste the login page | `login_url` | Almost always. The server takes the portal's address and the school key from it. |
| Name the parts | `portal_url` and `institution_key` | When you know them apart. |

Give one way or the other, not both. The address must start with `https://`. The server accepts `http://` only for `localhost`, `127.0.0.1`, and `::1`, for a portal on your own machine. An address that holds a user name or a password is refused.

Two more settings are rare. `label` is a name for people, and it shows in responses. `role_id` picks a role when the login has several, and the server tells you when it needs one.

Here is a file with two accounts.

```toml
[accounts.marta]
label = "Marta"
login_url = "https://portal.example.test/ACWeb/LogOn.aspx?key=your-school-key"
username = "env:PORTAL_MARTA_USERNAME"
password = "env:PORTAL_MARTA_PASSWORD"

[accounts.pablo]
label = "Pablo, other school"
portal_url = "https://other-portal.example.test"
institution_key = "other-school-key"
username = "env:PORTAL_PABLO_USERNAME"
password = "env:PORTAL_PABLO_PASSWORD"
```

## Children and their names in URLs

You do not configure children. The portal lists them, and the server names each one with a slug that it makes from the first name. The slug is lower case, uses letters and digits only, and joins words with hyphens, so `Ana Belén` becomes `ana-belen`. Two children with the same first name get `-2`, `-3`, and so on. The child with the smallest student id keeps the plain name.

A slug can change when a sibling joins and shares a first name. Pin a slug to a student id when other software depends on a URL.

```toml
[accounts.marta.slugs]
lucia = "5afe0000-0000-4000-8000-000000000101"
```

A pin keeps its slug exactly as written, and the other children work around it. A pin for a child that the portal no longer lists is ignored. Every URL also accepts the student id in place of the slug.

## The state directory

The server keeps its few files in `state_dir`.

| File | What it holds |
| --- | --- |
| `api-keys.json` | The hash of each API key, with its name, scopes, and accounts. The server cannot show a key again. |
| `breaker/NAME.json` | A pause on logins for one account, with its cause and the time. It holds no credential. |

The server creates the folder and its files so that only its own user can read them. Back up `api-keys.json` if you do not want to make keys again. A pause file is safe to delete, and `alexia-api accounts reset NAME` does so.

A relative `state_dir` starts at the folder of the configuration file, so the server and the key commands agree on the place from any folder. A relative path in the `ALEXIA_API_STATE_DIR` variable starts at the working folder instead, as a person who types it expects. Without a file or a variable the folder is `state` in the working folder. A path may start with `~`.

## Time zone

`timezone` is the school's time zone, and its default is `Europe/Madrid`. It decides what "today" means for the agenda and which offset a time carries. Every time in a response has an offset, such as `+02:00`, so it reads the same on both sides of a clock change. A server in another zone keeps the school's day when you leave the setting alone. Change it when the school is somewhere else.

## Be gentle with the portal

The server asks the school's portal as little as it can.

| Setting | What it controls |
| --- | --- |
| `cache` | How long each kind of answer is reused before the portal is asked again. The values are in seconds, and zero turns the reuse off for that kind. |
| `min_spacing_seconds` | The pause between two requests of one account. The least allowed is 0.1. |
| `request_timeout_seconds` | How long to wait for the portal to answer one request. |

A client can ask for a new read with `fresh=true`, but the server still keeps the pause between requests. Use `fresh=true` when you know something changed, and not on a timer.

## Protect the server

These settings matter when other machines can reach the server.

| Setting | What it does |
| --- | --- |
| `rate_limit_per_minute` | How many requests one API key may make each minute. Zero turns the limit off. |
| `docs_enabled` | Serves `/docs`, `/redoc`, and `/openapi.json`. The `/docs` page loads scripts from a public CDN in your browser, so turn this off on a server that is on the internet. |
| `allowed_hosts` | Answers only requests for these host names. A request for any other name gets the problem `invalid_host`. The two health checks answer for any name. |
| `cors_origins` | Lets web pages from these origins call the API in a browser. List the exact origins. The `doctor` command warns about `*`. |

Write a host as a bare name, such as `api.example.test`, or as `*.example.test` for every subdomain and not the domain itself. Write no `https://` and no port. The server compares names without regard to case and ignores the port in the request.

## Switches for features that come later

`allow_writes`, `allow_forms`, and `restore_unread` belong to calls that change things at the school. This version has no such calls, so the switches only change the capabilities that the server reports. They are off by default. `allow_forms` needs `allow_writes`, and the server stops at a setup that breaks this rule. The `doctor` command warns when any switch is on.

## Logging

`log_level` is `debug`, `info`, `warning`, or `error`. `log_format` is `text` for people or `json` for one object per line.

The server writes one line for each request. It names the method, the route, the status, the time taken, the request id, the names of the account and the key, and the `code` of the problem when the request failed. It names the route and not the address, so a child's name or a student id in a URL never reaches the log. An account name appears only when the request reached an account that you configured, so a name that a caller typed never appears. The log never holds a key, a password, or a message.

When a client quotes a `request_id`, search the log for it. The `code` on that line says why the request failed, and the [errors page](errors.md) explains each code.

## Check your setup

Run `doctor` after each change. Without `--online` nothing leaves your machine.

```bash
pixi run doctor
pixi run doctor --online
```

With `--online` the command opens the login page of each portal. It sends no password, so it cannot lock an account. The [troubleshooting guide](troubleshooting.md) explains each finding. The `serve` command runs the same checks before it starts, and it refuses to start while a line is marked `stop`.

## Examples

A laptop with one family needs a file and two variables.

```bash
pixi run init --account marta --login-url "https://portal.example.test/ACWeb/LogOn.aspx?key=your-school-key"
export PORTAL_MARTA_USERNAME="your user name"
export PORTAL_MARTA_PASSWORD="your password"
pixi run serve
```

Make a key from a second terminal in the same folder, with `pixi run keys create phone`.

A container needs no file at all. The volume keeps the keys when you replace the container.

```bash
docker build --tag alexia-familia-api .
docker run --detach --name alexia-api \
  --publish 127.0.0.1:8000:8000 \
  --volume alexia-data:/data \
  --env ALEXIA_API_ACCOUNTS__MARTA__LOGIN_URL="https://portal.example.test/ACWeb/LogOn.aspx?key=your-school-key" \
  --env ALEXIA_API_ACCOUNTS__MARTA__USERNAME="env:PORTAL_MARTA_USERNAME" \
  --env ALEXIA_API_ACCOUNTS__MARTA__PASSWORD="env:PORTAL_MARTA_PASSWORD" \
  --env PORTAL_MARTA_USERNAME \
  --env PORTAL_MARTA_PASSWORD \
  alexia-familia-api
docker exec alexia-api alexia-api keys create phone
```

The two `--env` options without a value pass your own variables of the same name into the container.
