# Authentication

Every data route needs an API key. The routes that say where the server is and whether it is up need none, and neither do `/docs`, `/redoc`, and `/openapi.json`.

A key is a long random text that starts with `afk_`. The server keeps only a hash of each key, so it can check a key and cannot show it again. Your portal password stays on the server. A key is the only secret that a client holds, and it lets that client read what the portal shows for the accounts of the key. Treat a key like a password.

## Make a key

```bash
pixi run keys create phone
```

The command prints a short report and then the key, which it shows once.

```text
Made the key phone with the scope read, for all accounts.
Copy it now. It is shown once, and the server keeps only a hash of it.
afk_...
```

The key goes to standard output and the report goes to standard error, so a script can capture the key and nothing else. A running server accepts a new key at once, without a restart.

A name is 1 to 40 lower case letters, digits, and hyphens. It tells keys apart, and it appears in the server's log. The log never holds a key. Give each program its own key, and the log shows which program made a call.

## Scopes

A scope is a kind of access. A key holds one or more, and a stronger scope includes the weaker ones.

| Scope | What it allows | It includes |
| --- | --- | --- |
| `read` | Everything the server reads. That covers the accounts, the children, the tracking counters, the staff, the agenda, the messages, the files, and the calendar files. It also covers checking an account's login. | `feed` |
| `feed` | Calendar files and nothing else. | Nothing |
| `write` | Calls that change things at the school. No route needs it yet. | `read`, `feed` |
| `admin` | Everything above, and lifting a pause on the logins of an account. | `write`, `read`, `feed` |

A key made without `--scope` holds `read`. Give a key the least scope that works. Repeat the option to give several scopes.

```bash
pixi run keys create calendar --scope feed
pixi run keys create operator --scope admin
```

This table shows what each route needs.

| Route | Scope |
| --- | --- |
| `/`, `/healthz`, `/readyz`, `/docs`, `/redoc`, `/openapi.json` | None |
| Accounts, children, tracking, staff, agenda as JSON, folders, messages, files | `read` |
| `POST /v1/accounts/{account}/connection/check` | `read` |
| `POST /v1/accounts/{account}/connection/reset` | `admin` |
| The three `agenda.ics` routes | `feed`, which every scope includes |

A key without the scope that a route needs gets `403` and the problem `insufficient_scope`. Its `needed` member names the scope.

## Accounts a key may use

A server can hold several accounts, for example one for each parent. A key may use all of them or only some.

```bash
pixi run keys create mother-phone --account marta
pixi run keys create both-calendar --scope feed --account marta --account pablo
```

Without `--account`, a key may use every account, now and in the future. A key limited to some accounts sees only those in `GET /v1/accounts`. A request for any other account gets `404` and the problem `account_not_found`, the same answer as for an account that does not exist, so a key cannot reveal which accounts the server holds.

The command does not need the account to exist yet. It only prints a note when the name is not in the settings, so you can make the key before you add the account.

## Send a key

| How | When to use it |
| --- | --- |
| `Authorization: Bearer KEY` | The usual way. |
| `X-API-Key: KEY` | A client that cannot set `Authorization`. |
| `?key=KEY` in the address | The calendar routes only, and only with a key that holds nothing but `feed`. |

A request that has both headers counts the bearer token.

```bash
curl -H "Authorization: Bearer $KEY" "http://127.0.0.1:8000/v1/accounts"
curl -H "X-API-Key: $KEY" "http://127.0.0.1:8000/v1/accounts"
```

A request without a key gets `401` and the problem `missing_api_key`. A key that the server does not know gets `401` and `invalid_api_key`. Both carry a `WWW-Authenticate` challenge. A key in `?key=` on a route that does not take it counts as no key.

## Calendar keys

A calendar app cannot send a header, so the key has to go into the address. An address ends up in settings, in chat messages, and in the logs of every proxy on the way. For that reason the server lets only a key that holds nothing but `feed` travel in an address.

```bash
pixi run keys create calendar --scope feed --account marta
```

```text
http://127.0.0.1:8000/v1/accounts/marta/agenda.ics?key=afk_...
```

A key with any other scope is refused in an address, even when it is the right key.

```json
{
  "type": "about:blank",
  "title": "Forbidden",
  "status": 403,
  "detail": "a key in a URL must hold only the feed scope, so send this key in a header, or make a key for the calendar with `alexia-api keys create NAME --scope feed`",
  "code": "key_not_allowed_in_url",
  "request_id": "579ea4d938ab47d584d96f4d90f99aa7"
}
```

Giving a key both `feed` and another scope makes it a normal key, so it can no longer travel in an address.

A leaked calendar address opens calendars and nothing else. It still shows the lessons, the school events, the teachers' names, and the first names of the children, until you revoke the key. Revoke it, make a new one, and update the apps that use it. The [calendar guide](calendars.md) shows how to subscribe.

## List and revoke keys

```bash
pixi run keys list
pixi run keys revoke phone
```

The list shows each key by name, never the key itself.

```text
NAME      SCOPES  ACCOUNTS     CREATED
phone     read    marta        2026-10-19
calendar  feed    marta,pablo  2026-10-19
ops       admin   *            2026-10-19
```

A running server notices the change and stops accepting a revoked key at once.

## Replace a key

Keys do not expire in this version. Replace one when it leaked, when a person left, or when you retire a program.

1. Make a new key with a new name.
2. Give it to the program.
3. Check that the program works.
4. Revoke the old key.

## Where keys are kept

The server keeps one file, `api-keys.json`, in its `state_dir`. For each key it holds the name, the scopes, the accounts, the date, and a SHA-256 hash. A key is 256 random bits, so nobody can work it out from the hash. The server compares every stored hash on each request, so the answer takes the same time whichever key matches.

The server creates the folder and the file so that only its own user can read them. A write goes to a temporary file first and then replaces the old one, so a crash cannot leave half a file. Back the file up if you do not want to make your keys again.

A file that cannot be read makes the server refuse every key. No command overwrites it, so you can look at it before you decide what to do. The `doctor` command reports it.

In a container, run the commands inside it, as the [deployment guide](deployment.md) shows. The keys then land in the volume that holds `state_dir`.

## When a key does not work

| You see | Why | What to do |
| --- | --- | --- |
| `missing_api_key` | The request carries no key. A key in `?key=` counts as none on a route that does not take it. | Send `Authorization: Bearer KEY`. |
| `invalid_api_key` | The server does not know the key. It may be revoked, mistyped, or from another server. | Look for a stray space or quote, or make a new key. |
| `key_not_allowed_in_url` | A calendar address carries a key that holds more than `feed`. | Make a key with `--scope feed` for the address. |
| `insufficient_scope` | The key lacks the scope that the route needs. | Use a key with the scope in `needed`. |
| `account_not_found` | No such account, or the key may not use it. | List the accounts with `GET /v1/accounts`, or make a key for the account. |
| `rate_limited` | The key made too many requests in a minute. | Wait for `Retry-After`. The [API guide](api-guide.md#rate-limits) explains the limit. |

The [errors page](errors.md) lists every code.

## The demo key

`pixi run demo` makes its own key, with the `admin` scope and every account. It lives in a temporary folder and goes away when you stop the demo. Do not copy it into real software.

## Keep keys safe

- Use `https` when the server is reachable from anywhere but your own computer. A key travels in every request, so plain `http` shows it to everyone on the way. The [deployment guide](deployment.md) shows how to add `https`.
- Give each program its own key and the least scope that works.
- Keep keys out of source control, screenshots, and chat messages.
- Prefer a header to an address. Use an address only for a calendar key.
- Revoke a key at once when you think it leaked.
