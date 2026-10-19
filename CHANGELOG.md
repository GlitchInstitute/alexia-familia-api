# Changelog

This file follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- Run a REST API with `alexia-api serve`, with a typed OpenAPI description at `/openapi.json` and documentation pages at `/docs` and `/redoc`.
- Read the children of an account, the counters the school tracks for each child, and the staff a guardian can meet.
- Read the absences and other attendance incidents of a child, with the day, the kind of incident, and whether a reason was given and accepted. The portal's page lists only the days since the start of the month, and the route says so.
- Read the agenda of a child and of the guardian as JSON, and subscribe to it as a calendar file for one child, for the guardian, or for the whole family.
- Read the message folders of an account, page through the messages of a folder or only the unread ones, read a message with its text, links, and files, and download an attachment.
- Hold several children on one login and several logins on one server. A route names a child by id or by a short name that stays stable.
- Protect the API with keys that carry scopes and a list of accounts. A key with only the `feed` scope may travel in a web address, so calendar apps can use it.
- Keep the account safe. The server sends one request at a time for each account, pauses between requests, and stops after a refused login until `alexia-api accounts reset` lifts the block.
- Answer every error with a problem document that has a stable `code` and a request id.
- Keep memory and traffic low with short per-account caches that share reads.
- Try the server without an account with `alexia-api demo`, which runs against a simulated school.
- Set up with `alexia-api init`, check the setup with `alexia-api doctor`, and manage keys with `alexia-api keys`.
- Run in a container. The image runs as a normal user, and the Compose file shows a full setup.
- Check health with `/healthz` and `/readyz`. Both answer for any host name, so a platform can probe with its own address.
- Use `pixi` for the environment, the tasks, and the lock file on Linux, macOS, and Windows.
- Subscribe a calendar app to the demo with the address that `alexia-api demo` prints. The key in that address opens calendars and nothing else.
- Write each timed calendar entry as a moment in UTC and each all-day entry as a date, so calendar apps agree on the hours and no app has to read time zone rules.
- Refuse a request for a host name that `allowed_hosts` does not list, so the API answers only under the names you chose.
- Stop at once, with a plain message, when `serve` or `demo` cannot listen on the address.
- Write one access line for each request with the route, the status, the time, the request id, the account, the key name, and the error code. It never holds the query string or a name that the caller typed.
- Read a secret from a file with `file:/path`, where `~` stands for the home folder.
- Publish a version by pushing a tag. The release workflow checks everything again, builds the package, pushes the image to the GitHub container registry, and creates the release with the notes from this file.
- Follow the guides for getting started, configuration, authentication, children and accounts, calendars, deployment, and troubleshooting, with a reference for every route, setting, and error code. The protocol notes say how sure each fact about the portal is.
