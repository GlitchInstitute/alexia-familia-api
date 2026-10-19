# Troubleshooting

Start with `doctor`. It checks your setup without calling the portal, and it says what to fix.

```bash
pixi run doctor
pixi run doctor --online
```

With `--online` it also opens the login page of each portal. It sends no password, so it cannot lock an account. This page follows the order in which things go wrong. First the server does not start, then the checks report a problem, and then requests fail.

## The server does not start

The `serve` command runs the same checks as `doctor`. It refuses to start while a line is marked `stop`, and it prints the line. Here are the messages that you may see first.

| You see | Why | What to do |
| --- | --- | --- |
| `the configuration file X does not exist` | The path after `-c` points at nothing. | Check the spelling, or write a file with `pixi run init`. |
| `ALEXIA_API_CONFIG points to X, which does not exist` | The variable names a file that is not there. | Fix the path, or remove the variable. |
| `X is not valid TOML` | The file has a syntax error. The message says where. | Check for text without quotes and for a table name that you wrote twice. |
| `the configuration has problems`, then lines such as `accounts.marta.login_url: ...` | Each line names a setting and what is wrong with it. | Fix each line. A message never shows a value, because a value may be a password. |
| `the environment has variables that are not settings` | A variable starts with `ALEXIA_API_` and names no setting. It is often a typo, and it is sometimes a secret that you named in that style. | Rename it. A secret variable must not start with `ALEXIA_API_`. |
| `some secrets cannot be read` | A variable is not set, or a file cannot be read. Each secret has its own line. | Set the variable in the shell that starts the server, or fix the path. In a container, pass the variable in with `--env`. |
| `no account is configured` | There is no account in the file or the environment. | Run `pixi run init`, or try `pixi run demo` first. |
| `X cannot be written` | The server cannot write its state directory. | Make the folder writable for the user that runs the server. In Docker, a folder that you mount needs `chown 10001:10001`. |
| `cannot listen on 127.0.0.1 port 8000, address already in use` | Another program uses the port. Both `serve` and `demo` check before they print anything else. | Use `--port 8001`, or stop the other program. A port below 1024 may also need more rights, and the message then says `permission denied`. |

Restart the server after you change a secret. It reads every secret once, when it starts.

## What `doctor` says

Each line has a level.

| Level | What it means |
| --- | --- |
| `ok` | Nothing to do. |
| `warn` | It works, but something is risky or untidy. |
| `fail` | The server can start, but something it needs is broken. |
| `stop` | The server cannot start until you fix it. |

The last line is the verdict, and `doctor` exits with status 1 when a line is `fail` or `stop`, so a script can use it as a check. This is a run for an account that is paused, with a portal address that is still the example.

```text
ok    config          read /home/you/alexia-api.toml
ok    accounts        1 configured, marta
fail  accounts.marta  the portal address is still the example portal.example.test
                      Fix: paste the address of your school's login page into login_url
ok    accounts.marta  user name from the variable PORTAL_MARTA_USERNAME, password from the variable PORTAL_MARTA_PASSWORD
fail  accounts.marta  logins are paused since 2026-10-18 09:12 +0200 because the portal rejected the user name or password
                      Fix: correct the user name or the password, and check that they work in a browser, then run `alexia-api accounts reset marta`
ok    state           /home/you/state can be written
fail  keys            no API key exists, so every request would be refused
                      Fix: run `alexia-api keys create NAME`

The server can start, but the lines marked fail need attention.
```

| Line | Level | What it means | What to do |
| --- | --- | --- | --- |
| `config` | `stop` | The configuration has a problem. The message is one from the table above. | Fix what it names, and run `doctor` again. |
| `accounts` | `stop` | No account is configured. | Run `pixi run init`, or try `pixi run demo` first. |
| `accounts.NAME` | `fail` | The portal address is still an example host, such as `portal.example.test`. | Paste the address of your school's login page into `login_url`. |
| `accounts.NAME` | `stop` | The user name or the password cannot be read. | Set the variable, or fix the file, and run `doctor` again. |
| `accounts.NAME` | `warn` | The password is written in the configuration file. | Use `env:NAME` or `file:/path`, so that the file holds no secret. |
| `accounts.NAME` | `fail` | Logins are paused after a failure that could lock the account. The line says why and since when. | Fix the cause as the line says, then run `alexia-api accounts reset NAME`. |
| `state` | `stop` | The state directory cannot be written. | Make it writable for the user that runs the server, or set `state_dir` elsewhere. |
| `keys` | `fail` | No API key exists, so every request would be refused. | Run `alexia-api keys create NAME`. |
| `keys` | `fail` | The file of keys cannot be read. | Fix the file or remove it, and make the keys again. |
| `keys` | `warn` | A key names an account that is not configured. | Revoke the key with `alexia-api keys revoke NAME`, or add the account. |
| `writes` | `warn` | A switch for calls that change things at the school is on. | Keep the switches off unless you need them. |
| `rate_limit` | `warn` | The limit on requests for each key is off. | Set `rate_limit_per_minute` to a number such as 120. |
| `cors` | `warn` | A web page from any origin may call the API from a browser. | List the exact origins in `cors_origins`. |
| `portal.NAME` | `fail` | The online check could not reach the login page, or the reply did not look like the portal's. The line says which. | Check the address and that this machine can reach the portal. A maintenance notice means to try again later. |

## A request fails

The [errors page](errors.md) lists every `code`. These are the cases that need more than one line.

### Every request says `breaker_open`

The server paused its logins to protect the account, because an earlier login failed in a way that could lock it. The pause survives a restart on purpose, so a crash loop cannot try the password again and again.

1. See why with `alexia-api accounts list`, or read `cause` and `since` in the problem.
2. Fix the cause. For a wrong password, correct the secret and check in a browser that it works. For `action_required_in_portal`, sign in with a browser and finish the step. The `interstitial` member of the first problem names the page. `CambiarPws` asks for a new password, `TxtLegales` asks you to accept legal texts, `OKCuenta` asks you to confirm the account, `MatOnline` offers online enrollment, and `Classroom` shows a classroom page.
3. Restart the server if you changed a secret.
4. Run `alexia-api accounts reset NAME`. A key with the `admin` scope can call `POST /v1/accounts/{account}/connection/reset` instead.

A reset allows one more login. Do it only after you checked the password in a browser, because a second wrong try can lock the account at the school.

### I changed my portal password

Change the secret that the server reads, restart the server, and run `alexia-api accounts reset NAME` if the old password paused the logins.

### A new sibling does not show up

The server reuses the list of children for 15 minutes. Ask for `GET /v1/accounts/{account}/children?fresh=true`, and the new child appears. A new sibling who shares a first name can also change the slug of another child, so read the `slug` in the list again. Pin the slugs that other software depends on. The [configuration guide](configuration.md#children-and-their-names-in-urls) shows how.

### The agenda is empty

- The range may be a holiday, a weekend, or the summer. An empty list is a real answer.
- A range with `kind` set keeps only that kind, so check that you did not filter everything out.
- The school's timetable for the far future is a guess, so lessons stop sooner than other events. The calendar feeds list lessons for 90 days and other events for 180 days by default.
- `from` and `to` are days at the school, and both count. Check that they are in the order you meant.
- Ask again with `fresh=true` if the school changed something a moment ago.

### A meeting shows the state `unknown`

The server reads the state from the word that the portal prints. It knows words for five states, and only `Aceptada` has been seen on a real list. Read `state_label` for the portal's own word. Open an issue with that word and nothing else, and the reader can learn it. The [protocol notes](protocol.md#meetings) list the stems that the reader matches.

### A teacher is not found, or has no free hours

- `staff_not_found` means that the id is not on the staff list of that child. Read `GET /v1/accounts/{account}/children/{child}/staff` and use an id from it. A teacher of a sibling does not count. Ask for the list with `fresh=true` when a teacher was added lately.
- An empty list means that the portal reports nothing free. The school sets the free hours, and a teacher can have none in a month. Ask for the next month with `month=YYYY-MM`.
- The answer is kept for a minute. Add `fresh=true` when you know that an hour was freed.

### The message list is shorter than the portal's

The list comes a page at a time. Follow `next_offset` until it is null. `truncated` is true when the folder is longer than the server reads, and then the oldest messages are left out.

### Does reading a message mark it as read?

The portal may mark a message as read when it opens, and this server cannot tell whether it does. Nobody has run the experiment that would show it, as the [protocol notes](protocol.md#what-nobody-has-seen) explain. The `read` field reports what the portal said when the list was loaded. Note it before you open a message if it matters to you.

### A time is off by one or two hours

A time such as `2026-03-30T09:00:00+02:00` is nine o'clock at the school. A program that converts it to UTC shows `07:00`, which names the same moment. Show the time in the school's zone, or keep the offset. Check `timezone` if the offset is wrong for your school.

A calendar file works differently. It writes each lesson as a moment in UTC, such as `20260330T070000Z`, and your calendar app shows that moment in the time zone of your device. A phone set to another zone shows other hours for the same lesson. Check the time zone of the device, and of the calendar app if it has a setting of its own. The [calendar guide](calendars.md#when-a-calendar-does-not-work) lists the other causes.

### `rate_limited`

One key made more requests than `rate_limit_per_minute` allows. Wait `retry_after_seconds` and ask less often. A calendar app that polls too fast needs a longer interval. Raise the limit only if the traffic is real.

### `invalid_host` behind a proxy

The proxy sends a `Host` header that `allowed_hosts` does not list. Make the proxy pass the original host name on, or add the name the proxy sends to `allowed_hosts`. The two health checks answer for any name, so a platform probe keeps working.

### A browser says there is a CORS error

The server answers a browser only for the origins in `cors_origins`. Write the exact origin, such as `https://app.example.test`, without a path and without a trailing slash. A request from any other origin gets a plain `400` answer to its preflight, and the browser reports it as a CORS error.

### A calendar app shows old events, or none

- A feed answers with a problem and not with a shorter calendar when the portal cannot be read, so an app keeps what it had. Open the address in a browser to see the problem.
- Calendar apps refresh on their own schedule, often every few hours, and the server cannot change that.
- A feed address with `?key=` needs a key that holds only the `feed` scope. A key with other scopes gets `key_not_allowed_in_url`.
- Quote the address in a shell, because `&` ends a command.

The [calendar guide](calendars.md#when-a-calendar-does-not-work) has a longer table of causes.

### `transport`, `ws_rejected`, or other `502` and `504` problems

The portal did not answer, or it answered with an error. Run `doctor --online` to see whether the login page answers. Try again later. Raise `request_timeout_seconds` only when the portal is slow and not down.

### `portal_changed` or `unexpected_reply`

The portal's pages or calls changed in a way the server does not know. Open an issue with the version from `alexia-api --version`, the `code`, the `request_id`, and the `detail`. The detail names the part that changed. Leave out names, student ids, message text, and anything else personal.

### `attachment_too_large`

The file is larger than `max_attachment_mib`, which is 25 by default. A file is held in memory while it travels, so raise the number only as far as you have memory for. You can also open the message in the portal.

### The `/docs` page is blank

The page loads its scripts from a public CDN in your browser, so it stays blank on a machine without internet or behind a blocker. Use the [endpoint reference](endpoints.md), or run `alexia-api openapi` and open the document in an editor.

## Docker

| You see | Why | What to do |
| --- | --- | --- |
| The container is `unhealthy` | The health check calls port 8000, and the command uses another port. | Change the port in the health check as well. |
| `permission denied` for `/data` | A folder that you mount belongs to another user. The container runs as user `10001`. | Run `chown 10001:10001` on the folder. |
| Keys vanish with a new container | `/data` has no volume. | Mount a volume at `/data`, as `compose.yaml` does. |
| Compose rejects the `env_file` entry | Compose is older than 2.24. | Update Compose. |
| `invalid_credentials` on the first start, and the password has a `$`, a `#`, or a quote | The value changed on its way in. Compose reads a `$` in an unquoted `.env` value as a variable, and `docker run --env-file` keeps quotes as part of the value. | Write the value in single quotes in the `.env` that Compose reads, and with no quotes in a file for `--env-file`. See [Passwords with special characters](deployment.md#passwords-with-special-characters). Reset the pause only after the value is right. |

## Windows

- In PowerShell, set a variable with `$env:PORTAL_MARTA_PASSWORD = 'your password'`. Use single quotes, because double quotes make PowerShell read a `$`, and a wrong password can lock your account. In Command Prompt, use `set PORTAL_MARTA_PASSWORD=your password`. Set it in the same window where you run `pixi run serve`.
- The [Windows section of the getting started guide](getting-started.md#windows) covers the rest, such as `curl.exe`.
- PowerShell 5 writes UTF-16 when you redirect with `>`. Use `pixi run openapi --output openapi.json` instead.
- Put an address with `&` in quotes, or the shell cuts it at the `&`.

## Ask for help

Open an issue on the project's GitHub page and pick the bug report form. Send these.

- The version from `alexia-api --version`.
- The output of `doctor`.
- The `code` and the `request_id` of a failed request.

Never send a password, an API key, a student id, a name, a message, or the address of your school's portal.
