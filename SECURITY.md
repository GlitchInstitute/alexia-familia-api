# Security policy

This server signs in to a school portal with a parent's real login and handles data about children. We take reports about it seriously, and we ask you to send them in private.

## Report a problem

Use the private form at [github.com/GlitchInstitute/alexia-familia-api/security/advisories/new](https://github.com/GlitchInstitute/alexia-familia-api/security/advisories/new). Please do not open a public issue or pull request for a security problem.

Tell us what you did, what you expected, and what happened. A short script or a request we can replay against `alexia-api demo` is the best proof, because the demo needs no account. Never send a real password, a real API key, or data about a real child. Replace them with made-up values.

We aim to answer within seven days and to tell you when a fix is expected. We credit you in the release notes unless you ask us not to.

## Supported versions

The project is young. Only the latest release gets fixes.

## What the server protects

- API keys are stored as SHA-256 hashes and compared in constant time. The server cannot show a key again after it is made.
- A key holds scopes and a list of accounts. A key for one account cannot read another.
- A key in a URL works only for calendar feeds, and only when it holds nothing but the `feed` scope.
- Portal passwords and user names are read from the environment or from a file, kept as secret strings, and never appear in a response, an error, a log line, or the OpenAPI document.
- The server stores no message, attachment, agenda, or child name on disk. The state folder holds key hashes and the block state of each account.
- A client never gives the server a web address. The server calls only the portal address in the configuration, so the API has no server-side request forgery surface.
- Every error is a problem document with a stable code and no stack trace. Every response has `Cache-Control: no-store`.
- Message HTML is cleaned with an allowlist before it is returned.
- After a login that the portal refuses, the server stops trying until an operator lifts the block. The block survives a restart, so a crash loop cannot lock the account.
- Logs hold the request id, the route template, the status, the time taken, the account name, the key name, and the code of a failed request. They hold no query values, no cookies, and no message text. An account name is logged only for an account the operator configured, because a caller types the address, and a name with a line break in it could forge a line of the log.

## What you have to do

The server is meant for a home network or a small private server. These steps keep it that way.

- Leave the server on `127.0.0.1` unless you put a reverse proxy with TLS in front of it. The Compose file in this repository publishes the port on `127.0.0.1` only.
- Treat an API key like a password. Make one key for each app with `alexia-api keys create`, give it the least scope that works, and revoke it with `alexia-api keys revoke` when the app goes away.
- Use a `feed` key for calendar subscriptions. It is the only kind that may travel in a URL, and it opens nothing but calendars.
- Keep portal passwords out of the configuration file. Write `env:NAME` or `file:/path` instead.
- Turn off the documentation pages with `docs_enabled = false` when the server is on the internet, because they load scripts from a public CDN in your browser.
- Set `allowed_hosts` to the names you serve, and set `cors_origins` only for web pages you trust.
- Leave `allow_writes` off unless you need it. Sending something to the school cannot be undone.

## In scope

- A request that gets around a key, a scope, or the list of accounts a key may use.
- A way to read a secret or a child's data from a log, an error, a response header, or the documentation.
- An injection, a path traversal, or a header injection, for example through a message, a file name, or a child's name.
- Message HTML that survives cleaning with a script or an active element in it.
- A small request that exhausts memory or keeps the server busy for long.
- A way to make the server call an address other than the configured portal.
- A problem in the container image, such as a process that runs as root.

## Out of scope

- A flaw in the school's portal. Report that to the school or to the makers of the portal.
- Running the server on an untrusted network without TLS, which these pages tell you not to do.
- An attacker who already controls the machine, the environment, or the files of the operator.
- The made-up logins and keys of the demo, which exist only to be tried.
- A report from an automated scanner with no description of the impact.

## How we handle a report

We confirm the problem, fix it in private, release the fix, and then publish an advisory that says what was wrong and which versions it touched.
