# Endpoint reference

This page comes from the code, so do not edit it by hand. Run `pixi run -e dev docs` to write it again.

An unofficial JSON API for the Alexia Familia parent portal. You run it yourself. It signs in to your own account and serves what the school shows you about your children.

**Keys.** Send an API key as `Authorization: Bearer <key>` or in the `X-API-Key` header. Make keys with `alexia-api keys create`. A key holds scopes (`read`, `write`, `admin`, `feed`) and a list of accounts it may use. The calendar feeds also take a key that holds only the `feed` scope as `?key=`, because a calendar app cannot send a header.

**Caching.** The server keeps each answer for a short time so that it stays gentle with the school's system. The `X-Cache` and `Age` headers say how an answer was found. Add `fresh=true` to ask the portal again.

**Errors.** Every failure is an RFC 9457 problem document with a stable `code` and a `request_id`. A 503 means the account cannot be used until the operator acts, for example after a wrong password. A 502 or a 504 means the portal misbehaved or did not answer.

Every route lives at the address of your server, for example `http://127.0.0.1:8000`. The [API guide](api-guide.md) explains what all routes share, such as ids, times, paging, and the headers that tell you how fresh an answer is.

## All routes

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/` | [Describe this server](#describe-this-server) |
| GET | `/healthz` | [Report that the process is alive](#report-that-the-process-is-alive) |
| GET | `/readyz` | [Report whether the server can serve requests](#report-whether-the-server-can-serve-requests) |
| GET | `/v1/accounts` | [List the accounts this key may use](#list-the-accounts-this-key-may-use) |
| GET | `/v1/accounts/{account}` | [Show one account](#show-one-account) |
| POST | `/v1/accounts/{account}/connection/check` | [Make sure the account has a working portal session](#make-sure-the-account-has-a-working-portal-session) |
| POST | `/v1/accounts/{account}/connection/reset` | [Lift a block on automatic logins](#lift-a-block-on-automatic-logins) |
| GET | `/v1/accounts/{account}/children` | [List the children of an account](#list-the-children-of-an-account) |
| GET | `/v1/accounts/{account}/children/{child}` | [Show one child](#show-one-child) |
| GET | `/v1/accounts/{account}/children/{child}/tracking` | [Show the tracking counters of a child](#show-the-tracking-counters-of-a-child) |
| GET | `/v1/accounts/{account}/children/{child}/staff` | [List the staff a guardian can meet about a child](#list-the-staff-a-guardian-can-meet-about-a-child) |
| GET | `/v1/accounts/{account}/children/{child}/absences` | [List the absences of a child](#list-the-absences-of-a-child) |
| GET | `/v1/accounts/{account}/children/{child}/meetings` | [List the meetings of a child](#list-the-meetings-of-a-child) |
| GET | `/v1/accounts/{account}/children/{child}/staff/{staff}/availability` | [List the days on which a member of the staff has a free hour](#list-the-days-on-which-a-member-of-the-staff-has-a-free-hour) |
| GET | `/v1/accounts/{account}/children/{child}/staff/{staff}/availability/{day}` | [List the free slots of a member of the staff on one day](#list-the-free-slots-of-a-member-of-the-staff-on-one-day) |
| GET | `/v1/accounts/{account}/children/{child}/agenda` | [Show the agenda of a child](#show-the-agenda-of-a-child) |
| GET | `/v1/accounts/{account}/guardian/agenda` | [Show the agenda of the guardian](#show-the-agenda-of-the-guardian) |
| GET | `/v1/accounts/{account}/children/{child}/agenda.ics` | [Subscribe to the calendar of a child](#subscribe-to-the-calendar-of-a-child) |
| GET | `/v1/accounts/{account}/guardian/agenda.ics` | [Subscribe to the calendar of the guardian](#subscribe-to-the-calendar-of-the-guardian) |
| GET | `/v1/accounts/{account}/agenda.ics` | [Subscribe to one calendar for the whole family](#subscribe-to-one-calendar-for-the-whole-family) |
| GET | `/v1/accounts/{account}/folders` | [List the message folders of an account](#list-the-message-folders-of-an-account) |
| GET | `/v1/accounts/{account}/messages` | [List the messages in a folder](#list-the-messages-in-a-folder) |
| GET | `/v1/accounts/{account}/messages/{message}` | [Read one message](#read-one-message) |
| GET | `/v1/accounts/{account}/messages/{message}/attachments/{attachment}` | [Download one file of a message](#download-one-file-of-a-message) |

## Routes for meta

Is the server up, and where is everything.

### Describe this server

`GET /`

Names the server and says where its documentation and health checks are.

**Key.** None. This route is open to anyone who can reach the server.

**Answers**

- `200` returns [Index](#index) as `application/json`.

### Report that the process is alive

`GET /healthz`

Answers 200 whenever the process runs. It does not look at the portal, the accounts, or the key file, so a container can use it as a liveness check. It answers for any host name, even when `allowed_hosts` is set, because a platform probes with its own address.

**Key.** None. This route is open to anyone who can reach the server.

**Answers**

- `200` returns [Health](#health) as `application/json`.

### Report whether the server can serve requests

`GET /readyz`

Answers 200 when at least one account and at least one API key are configured, the key file can be read, and the state directory is writable. Otherwise it answers 503 and names the checks that failed. It never calls the portal. It answers for any host name, like the liveness check.

**Key.** None. This route is open to anyone who can reach the server.

**Answers**

- `200` returns [Readiness](#readiness) as `application/json`.

A failure answers `503` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

## Routes for accounts

The portal accounts this server holds, and their state.

### List the accounts this key may use

`GET /v1/accounts`

Needs the `read` scope. It lists the accounts the key is allowed to use, with the state of each connection. It never calls the portal, so it is cheap and safe to poll.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Answers**

- `200` returns [AccountList](#accountlist) as `application/json`.

A failure answers `401`, `403`, `429`, or `500` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

### Show one account

`GET /v1/accounts/{account}`

Needs the `read` scope. It shows the state of the connection, which switches the operator turned on, and how many children the last login listed. It never calls the portal.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `account` | text | The account's name, as the operator wrote it in the settings. |

**Answers**

- `200` returns [Account](#account) as `application/json`.

A failure answers `401`, `403`, `404`, `422`, `429`, or `500` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

### Make sure the account has a working portal session

`POST /v1/accounts/{account}/connection/check`

Needs the `read` scope. It uses the session the server has when that still works, and logs in when it does not. A login failure that could lock the account pauses automatic logins until an operator resets the block. Use this to test new credentials.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `account` | text | The account's name, as the operator wrote it in the settings. |

**Answers**

- `200` returns [ConnectionCheck](#connectioncheck) as `application/json`.

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

### Lift a block on automatic logins

`POST /v1/accounts/{account}/connection/reset`

Needs the `admin` scope. Run this only after you fixed the cause, which means correcting the password or finishing a step in the portal in a browser. The next request that needs the portal logs in again.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `account` | text | The account's name, as the operator wrote it in the settings. |

**Answers**

- `200` returns [ConnectionReset](#connectionreset) as `application/json`.

A failure answers `401`, `403`, `404`, `422`, `429`, or `500` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

## Routes for children

The children of an account and their school data.

### List the children of an account

`GET /v1/accounts/{account}/children`

Needs the `read` scope. Each child has a student id and a slug, and either one works in the other child routes. The list is stored for a while, so ask with `fresh=true` after a sibling joins the school.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `account` | text | The account's name, as the operator wrote it in the settings. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `fresh` | true or false | `false` | Ignore the stored answer and ask the portal again. The server still paces its requests, so use this when you know something changed and not on a timer. |

**Answers**

- `200` returns [ChildList](#childlist) as `application/json`.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

### Show one child

`GET /v1/accounts/{account}/children/{child}`

Needs the `read` scope. The child is found in the list the portal gave for this account, so a student id that belongs to another account is not found.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `child` | text | A student id, or the child's slug as the list of children shows it. Letter case does not matter. |
| `account` | text | The account's name, as the operator wrote it in the settings. |

**Answers**

- `200` returns [Child](#child) as `application/json`.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

### Show the tracking counters of a child

`GET /v1/accounts/{account}/children/{child}/tracking`

Needs the `read` scope. These are the five numbers in the portal's tracking widget, which count open tasks, activities, notes, tests, and incidents.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `account` | text | The account's name, as the operator wrote it in the settings. |
| `child` | text | A student id, or the child's slug as the list of children shows it. Letter case does not matter. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `fresh` | true or false | `false` | Ignore the stored answer and ask the portal again. The server still paces its requests, so use this when you know something changed and not on a timer. |

**Answers**

- `200` returns [TrackingCounters](#trackingcounters) as `application/json`.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

### List the staff a guardian can meet about a child

`GET /v1/accounts/{account}/children/{child}/staff`

Needs the `read` scope. These are the teachers and other staff the portal offers for a meeting request. Use the id of a person to ask when that person has a free hour, with the routes under `staff/{staff}/availability`.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `account` | text | The account's name, as the operator wrote it in the settings. |
| `child` | text | A student id, or the child's slug as the list of children shows it. Letter case does not matter. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `fresh` | true or false | `false` | Ignore the stored answer and ask the portal again. The server still paces its requests, so use this when you know something changed and not on a timer. |

**Answers**

- `200` returns [StaffList](#stafflist) as `application/json`.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

## Routes for absences

The absences and other attendance incidents the portal lists for a child.

### List the absences of a child

`GET /v1/accounts/{account}/children/{child}/absences`

Needs the `read` scope. This is the list on the portal's page for justifying absences, newest day first. Most entries are absences. Some are other incidents, such as a late arrival, so read `incident` for what happened and `justifiable` to see whether the portal lets a guardian justify it. The portal decides which days the list covers. Its page filters by the current month, so older absences may be missing, and an empty list does not prove that a child has none. This server only reads the list. A guardian justifies an absence in the portal itself. No real list of incidents has been read while building this route, so a row that is worded in a way the server does not know fails with `portal_changed`.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `account` | text | The account's name, as the operator wrote it in the settings. |
| `child` | text | A student id, or the child's slug as the list of children shows it. Letter case does not matter. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `fresh` | true or false | `false` | Ignore the stored answer and ask the portal again. The server still paces its requests, so use this when you know something changed and not on a timer. |

**Answers**

- `200` returns [AbsenceList](#absencelist) as `application/json`.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

## Routes for agenda

The lessons, interviews, and school events of each child and of the guardian, as data and as calendar files that a calendar app can subscribe to.

### Show the agenda of a child

`GET /v1/accounts/{account}/children/{child}/agenda`

Needs the `read` scope. Gives the lessons and the school events of one child for a range of days, earliest first. `from` and `to` are days at the school, written YYYY-MM-DD, and both count. Without them the range is today and the six days after it. A range covers at most 366 days and lies within 1100 days of today. A range that breaks these rules, or that ends before it starts, is refused with the code `invalid_window`. A lesson names its teacher and carries the numbers the school flagged for it, which are tasks, activities, notes, and tests, and whether a substitute teacher takes it. A holiday is a school event whose title the school writes as `festivo`. A time has the offset the school has on that day, so it reads the same on both sides of a clock change. The portal answers a range with far more than was asked for, so the server keeps only the days you asked for. Each range is stored on its own for a while, and `fresh=true` reads it again. The portal shows one agenda at a time for a login, so this read waits for the other requests of the same account.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `account` | text | The account's name, as the operator wrote it in the settings. |
| `child` | text | A student id, or the child's slug as the list of children shows it. Letter case does not matter. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `kind` | list of one of `"lesson"`, `"interview"`, `"holiday"`, `"school_event"` or null | none | Keep only entries of this kind. Repeat the parameter to keep several kinds, as in `kind=lesson&kind=interview`. Leave it out to keep every kind. |
| `fresh` | true or false | `false` | Ignore the stored answer and ask the portal again. The server still paces its requests, so use this when you know something changed and not on a timer. |
| `from` | date, written `YYYY-MM-DD` or null | none | The first day of the range, written YYYY-MM-DD, counting that day. The default is today at the school. |
| `to` | date, written `YYYY-MM-DD` or null | none | The last day of the range, written YYYY-MM-DD, counting that day. The default is 6 days after `from`, so that the range is a week. |

**Answers**

- `200` returns [Agenda](#agenda) as `application/json`.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

### Show the agenda of the guardian

`GET /v1/accounts/{account}/guardian/agenda`

Needs the `read` scope. Gives the interviews with the school and the school events that the portal shows the guardian, for a range of days, earliest first. The range works as it does for a child, down to the `invalid_window` refusal. A login for which the portal lists no guardian has no such agenda, and the answer is a 404 with the code `guardian_not_found`. `fresh=true` also reads the list of children again, so a guardian that the portal has just begun to list is found.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `account` | text | The account's name, as the operator wrote it in the settings. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `kind` | list of one of `"lesson"`, `"interview"`, `"holiday"`, `"school_event"` or null | none | Keep only entries of this kind. Repeat the parameter to keep several kinds, as in `kind=lesson&kind=interview`. Leave it out to keep every kind. |
| `fresh` | true or false | `false` | Ignore the stored answer and ask the portal again. The server still paces its requests, so use this when you know something changed and not on a timer. |
| `from` | date, written `YYYY-MM-DD` or null | none | The first day of the range, written YYYY-MM-DD, counting that day. The default is today at the school. |
| `to` | date, written `YYYY-MM-DD` or null | none | The last day of the range, written YYYY-MM-DD, counting that day. The default is 6 days after `from`, so that the range is a week. |

**Answers**

- `200` returns [Agenda](#agenda) as `application/json`.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

### Subscribe to the calendar of a child

`GET /v1/accounts/{account}/children/{child}/agenda.ics`

Needs the `feed` scope, which every other scope includes. Gives an iCalendar file that a calendar app can subscribe to, with the lessons, the school events, and the holidays of one child. It reaches back `back` days and ahead `ahead` days from today at the school, and it lists lessons only for the next `lessons_ahead` days. A holiday or any other entry that lasts all day shows as free time. A lesson says its teacher and what the school flagged for it. Calendar apps cannot send a header, so this route also takes the key as `?key=`, but only a key that holds nothing but the `feed` scope. Make one with `alexia-api keys create NAME --scope feed`. A key with another scope is refused in a URL even when it is right, so an address that leaks opens calendars and nothing else. There is no `fresh` option, because this address is meant to be handed to other software. When the portal cannot be read, the answer is a problem and not a shorter calendar, so an app keeps what it had.

**Key.** Send one as `Authorization: Bearer <key>`, `X-API-Key: <key>`, or `?key=<key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `account` | text | The account's name, as the operator wrote it in the settings. |
| `child` | text | A student id, or the child's slug as the list of children shows it. Letter case does not matter. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `back` | whole number, at least 0 and at most 366 | `14` | How many days before today the calendar reaches. |
| `ahead` | whole number, at least 0 and at most 366 | `180` | How many days after today the calendar reaches. |
| `lessons_ahead` | whole number, at least 0 and at most 366 | `90` | How many days after today lessons are listed. The school's timetable for the far future is only a guess, and holidays and changes have not reached it, so lessons stop sooner than the rest. |

**Answers**

- `200` returns a file as `text/calendar`. An iCalendar file.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

### Subscribe to the calendar of the guardian

`GET /v1/accounts/{account}/guardian/agenda.ics`

Needs the `feed` scope, which every other scope includes. Gives an iCalendar file with the interviews and the school events that the portal shows the guardian. It reaches back `back` days and ahead `ahead` days from today at the school. A login for which the portal lists no guardian has no such calendar, and the answer is a 404 with the code `guardian_not_found`. Calendar apps cannot send a header, so this route also takes the key as `?key=`, but only a key that holds nothing but the `feed` scope. Make one with `alexia-api keys create NAME --scope feed`. A key with another scope is refused in a URL even when it is right, so an address that leaks opens calendars and nothing else. There is no `fresh` option, because this address is meant to be handed to other software. When the portal cannot be read, the answer is a problem and not a shorter calendar, so an app keeps what it had.

**Key.** Send one as `Authorization: Bearer <key>`, `X-API-Key: <key>`, or `?key=<key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `account` | text | The account's name, as the operator wrote it in the settings. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `back` | whole number, at least 0 and at most 366 | `14` | How many days before today the calendar reaches. |
| `ahead` | whole number, at least 0 and at most 366 | `180` | How many days after today the calendar reaches. |

**Answers**

- `200` returns a file as `text/calendar`. An iCalendar file.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

### Subscribe to one calendar for the whole family

`GET /v1/accounts/{account}/agenda.ics`

Needs the `feed` scope, which every other scope includes. Gives one iCalendar file with the lessons and school events of every child of the account and the guardian's interviews. Each entry of a child starts with the child's first name, or with the first name and the slug when two children share a first name. A holiday that the whole school shares appears once and has no name in front of it. Lessons stop after `lessons_ahead` days, as for a single child. The file is all or nothing, so one child whose agenda cannot be read fails the whole file, and a calendar app does not take the missing entries for entries that the school removed. Calendar apps cannot send a header, so this route also takes the key as `?key=`, but only a key that holds nothing but the `feed` scope. Make one with `alexia-api keys create NAME --scope feed`. A key with another scope is refused in a URL even when it is right, so an address that leaks opens calendars and nothing else. There is no `fresh` option, because this address is meant to be handed to other software. When the portal cannot be read, the answer is a problem and not a shorter calendar, so an app keeps what it had.

**Key.** Send one as `Authorization: Bearer <key>`, `X-API-Key: <key>`, or `?key=<key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `account` | text | The account's name, as the operator wrote it in the settings. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `back` | whole number, at least 0 and at most 366 | `14` | How many days before today the calendar reaches. |
| `ahead` | whole number, at least 0 and at most 366 | `180` | How many days after today the calendar reaches. |
| `lessons_ahead` | whole number, at least 0 and at most 366 | `90` | How many days after today lessons are listed. The school's timetable for the far future is only a guess, and holidays and changes have not reached it, so lessons stop sooner than the rest. |

**Answers**

- `200` returns a file as `text/calendar`. An iCalendar file.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

## Routes for meetings

The meetings of a child with the school, and the days and hours that a member of the staff has free for a new one.

### List the meetings of a child

`GET /v1/accounts/{account}/children/{child}/meetings`

Needs the `read` scope. This is the list on the portal's page of meetings for the child, in the order the meetings take place, oldest first. Each meeting has a `state`, which this server reads from the word the portal prints, and that word in `state_label`. Only the word `Aceptada` has been seen on a real list. A word that this server does not know reads as `unknown`, so branch on `state_label` for those. A meeting that a school holds for a whole group has been seen with the start 00:00 and the time of day in `note`. A time has the offset the school has on that day. This server only reads the list. Asking for a meeting, answering one, and cancelling one happen in the portal. A row that is worded in a way the server does not know fails with `portal_changed`.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `account` | text | The account's name, as the operator wrote it in the settings. |
| `child` | text | A student id, or the child's slug as the list of children shows it. Letter case does not matter. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `fresh` | true or false | `false` | Ignore the stored answer and ask the portal again. The server still paces its requests, so use this when you know something changed and not on a timer. |

**Answers**

- `200` returns [MeetingList](#meetinglist) as `application/json`.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

### List the days on which a member of the staff has a free hour

`GET /v1/accounts/{account}/children/{child}/staff/{staff}/availability`

Needs the `read` scope. Gives the days of one month on which a member of the staff has at least one free hour for a meeting, earliest first and each day once. `staff` is an id from the staff list of the same child, and any other id is a 404 with the code `staff_not_found`. `month` is written YYYY-MM and defaults to the current month at the school. A month that starts more than 1100 days from today is refused with the code `invalid_window`. The answer belongs to the person, so two children who share a teacher share the stored answer. It is kept for a minute by default, because other guardians book hours too, and `fresh=true` reads it again. An empty list means that nothing is free in that month. This server only reads the hours. Asking for a meeting happens in the portal.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `staff` | text | The id of a member of the staff, as the staff list of the same child shows it. Letter case does not matter. |
| `account` | text | The account's name, as the operator wrote it in the settings. |
| `child` | text | A student id, or the child's slug as the list of children shows it. Letter case does not matter. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `month` | text or null | none | The month to look at, written YYYY-MM. The default is the current month at the school. The month must start within 1100 days of today. |
| `fresh` | true or false | `false` | Ignore the stored answer and ask the portal again. The server still paces its requests, so use this when you know something changed and not on a timer. |

**Answers**

- `200` returns [AvailableDays](#availabledays) as `application/json`.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

### List the free slots of a member of the staff on one day

`GET /v1/accounts/{account}/children/{child}/staff/{staff}/availability/{day}`

Needs the `read` scope. Gives the free slots of a member of the staff on one day, earliest first, each with a start and an end that carry the school's offset. `staff` and the way the answer is kept work as they do for the days of a month. `day` is written YYYY-MM-DD, and a day more than 1100 days from today is refused with the code `invalid_window`. An empty list means that nothing is free on that day. This server only reads the hours. Asking for a meeting happens in the portal.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `staff` | text | The id of a member of the staff, as the staff list of the same child shows it. Letter case does not matter. |
| `day` | date, written `YYYY-MM-DD` | The day to look at, written YYYY-MM-DD. |
| `account` | text | The account's name, as the operator wrote it in the settings. |
| `child` | text | A student id, or the child's slug as the list of children shows it. Letter case does not matter. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `fresh` | true or false | `false` | Ignore the stored answer and ask the portal again. The server still paces its requests, so use this when you know something changed and not on a timer. |

**Answers**

- `200` returns [AvailableHours](#availablehours) as `application/json`.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

## Routes for messages

The message folders of an account and the messages in them.

### List the message folders of an account

`GET /v1/accounts/{account}/folders`

Needs the `read` scope. This server serves the received and the sent folders. The `count` of a folder is the number the portal prints after its name. The portal does not say whether it counts every message or only the unread ones, so use it as a hint.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `account` | text | The account's name, as the operator wrote it in the settings. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `fresh` | true or false | `false` | Ignore the stored answer and ask the portal again. The server still paces its requests, so use this when you know something changed and not on a timer. |

**Answers**

- `200` returns [FolderList](#folderlist) as `application/json`.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

### List the messages in a folder

`GET /v1/accounts/{account}/messages`

Needs the `read` scope. Messages come newest first, a page at a time. The portal belongs to the guardian and not to a child, so the list holds the messages for every child of the account. The server reads the whole folder from the portal once and stores it, so paging through it costs the portal a single read. Ask with `fresh=true` to see a message that arrived a moment ago.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `account` | text | The account's name, as the operator wrote it in the settings. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `folder` | one of `"received"`, `"sent"` | `"received"` | Which folder to list. |
| `unread` | true or false or null | none | `true` keeps the messages that are not known to be read. `false` keeps the ones that were read. Leave it out to keep every message. |
| `limit` | whole number, at least 1 and at most 100 | `25` | The most messages to return in one page. |
| `offset` | whole number, at least 0 | `0` | How many matching messages to skip. |
| `fresh` | true or false | `false` | Ignore the stored answer and ask the portal again. The server still paces its requests, so use this when you know something changed and not on a timer. |

**Answers**

- `200` returns [MessagePage](#messagepage) as `application/json`.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

### Read one message

`GET /v1/accounts/{account}/messages/{message}`

Needs the `read` scope. Gives the message as the list shows it, together with when the school sent it, its words, the addresses in them, and its files. The message must be in the list of the folder you name, so a message the family sent needs `folder=sent`. `body.html` is safe to show, and `body.text` holds the same words as plain text. The server stores a message after it reads it, so asking again is cheap. `fresh=true` reads the message again, and the list of its folder too. Opening a message in the portal may mark it as read there, and this server cannot tell whether it does. The `read` field comes from the list, so it shows the state from before the message was opened.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `message` | text | The message's id, as the list of messages shows it. Letter case does not matter. |
| `account` | text | The account's name, as the operator wrote it in the settings. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `folder` | one of `"received"`, `"sent"` | `"received"` | The folder the message is in. A message the family sent is in `sent`. |
| `fresh` | true or false | `false` | Ignore the stored answer and ask the portal again. The server still paces its requests, so use this when you know something changed and not on a timer. |

**Answers**

- `200` returns [Message](#message) as `application/json`.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the answer was stored, `miss` when it was just read from the portal, `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

A failure answers `401`, `403`, `404`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

### Download one file of a message

`GET /v1/accounts/{account}/messages/{message}/attachments/{attachment}`

Needs the `read` scope. Gives the bytes of one file that the `attachments` of the message list. The server fetches the file from the portal every time and keeps nothing, so you always get the file as it is now. The message must be in the list of the folder you name, so a message the family sent needs `folder=sent`. A file larger than the operator's `max_attachment_mib` is refused with a 413 and the code `attachment_too_large`. The portal sends every file as a plain stream of bytes, so the `Content-Type` is judged from the first bytes of the file. A web page or a vector picture is never named as one. It comes as `text/plain`, so a client that shows a file by its type cannot be made to run it. The answer always asks the client to save the file. `fresh=true` reads the list of the message's folder again, which a message that arrived a moment ago needs.

**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`.

**Path parameters**

| Name | Kind | What it is |
| --- | --- | --- |
| `message` | text | The message's id, as the list of messages shows it. Letter case does not matter. |
| `attachment` | text | The file's id, as the `attachments` of the message show it. Use it as it is, because it is an opaque token and not the portal's own id. |
| `account` | text | The account's name, as the operator wrote it in the settings. |

**Query parameters**

| Name | Kind | Default | What it does |
| --- | --- | --- | --- |
| `folder` | one of `"received"`, `"sent"` | `"received"` | The folder the message is in. A message the family sent is in `sent`. |
| `fresh` | true or false | `false` | Ignore the stored answer and ask the portal again. The server still paces its requests, so use this when you know something changed and not on a timer. |

**Answers**

- `200` returns a file as `*/*`. The file itself.

The `200` answer carries these headers.

| Header | What it says |
| --- | --- |
| `Content-Disposition` | Always `attachment`, with the file's name in a form that is safe to save under. |

A failure answers `401`, `403`, `404`, `413`, `422`, `429`, `500`, `502`, `503`, or `504` with a [Problem](#problem) as `application/problem+json`. The [errors page](errors.md) lists every `code`.

## Models

### Absence

One attendance incident of a child, such as a missed day or a late arrival.

The portal lists these on its page for justifying absences. Most are absences, and some are
other incidents, so `incident` holds the portal's own words for what happened.

| Field | Kind | What it says |
| --- | --- | --- |
| `id` | text | The portal's incident id. |
| `occurred_on` | date, written `YYYY-MM-DD` | The day of the incident, on the school's calendar. |
| `hour` | text or null | What the portal prints in its hour column, as text, for an incident that belongs to a time of the day. Null for an incident that covers the whole day. |
| `area` | text or null | The area or subject the portal files the incident under. |
| `teacher` | text or null | The teacher the portal names for the incident. |
| `incident` | text | The portal's own words for what happened, in the school's language. |
| `note` | text or null | The note the school wrote about the incident. |
| `justifiable` | true or false | False when the portal marks the incident as one that cannot be justified. |
| `justified` | true or false or null | Whether the guardian has justified the incident. Null when the portal's cell is neither a yes nor a no. |
| `justification` | text or null | The reason that was given when it was justified. |
| `accepted` | true or false or null | Whether the school accepted the justification. Null when the portal's cell is neither a yes nor a no. |

### AbsenceList

The attendance incidents the portal lists for one child, newest day first.

| Field | Kind | What it says |
| --- | --- | --- |
| `items` | list of [Absence](#absence) |  |

### Account

One set of portal credentials. It holds the children that the portal lists for it.

| Field | Kind | What it says |
| --- | --- | --- |
| `id` | text | The account's short name in URLs, chosen by the operator. |
| `label` | text | A name for people, for example the guardian's first name. It also names the family calendar and the guardian calendar. |
| `portal_host` | text | The host name of the portal this account signs in to. |
| `connection` | one of [LoggedOut](#loggedout), [LoggedIn](#loggedin), [Blocked](#blocked), told apart by `state` |  |
| `capabilities` | [Capabilities](#capabilities) |  |
| `child_count` | whole number or null | Children seen at the last login, or null before the first login. |

### AccountList

| Field | Kind | What it says |
| --- | --- | --- |
| `items` | list of [Account](#account) |  |

### Agenda

The entries of an agenda over a range of days, in the order they happen.

| Field | Kind | What it says |
| --- | --- | --- |
| `from` | date, written `YYYY-MM-DD` | The first day of the range, inclusive. It is the day that was asked for. |
| `to` | date, written `YYYY-MM-DD` | The last day of the range, inclusive. |
| `items` | list of [AgendaEvent](#agendaevent) | The entries that touch the range, earliest first, with the kinds asked for. |

### AgendaEvent

One entry of the school agenda.

| Field | Kind | What it says |
| --- | --- | --- |
| `id` | text | Names this occurrence and no other. The portal gives a lesson the same id every week, so this id is the portal's id, a `\|`, and the day, as in `<id>\|2026-10-19`. |
| `kind` | one of `"lesson"`, `"interview"`, `"holiday"`, `"school_event"` | `lesson` for a lesson of the timetable, `interview` for a meeting with a teacher, `holiday` for a school event that the school titles `festivo`, and `school_event` for everything else the school puts in the agenda. |
| `title` | text | The title as the school writes it, in the school's language. |
| `teacher` | text or null | The teacher the portal names for the entry, or null when it names none. |
| `starts_at` | date and time with an offset | When the entry starts, with the school's offset. The portal writes local time and marks it as UTC by mistake, and this server puts the right offset on it. |
| `ends_at` | date and time with an offset | When the entry ends, with the school's offset. |
| `all_day` | true or false | True when the entry covers whole days. The portal gives such an entry the times 00:00 and 00:00 or 23:59, and the days it covers run from `starts_at` to `ends_at`. |
| `signals` | [LessonSignals](#lessonsignals) or null | What the school flags on a lesson. Null for any other kind of entry. |

### Attachment

A file that came with a message.

| Field | Kind | What it says |
| --- | --- | --- |
| `id` | text | A token that names the file within its message. Treat it as opaque. It is safe to put in a URL path, and the download address of the file ends with it. |
| `name` | text | The file's name as the sender gave it. |
| `size` | whole number, at least 0 | The file's size in bytes, as the portal lists it. |

### AvailableDays

The days of one month on which a member of the staff has a free hour.

| Field | Kind | What it says |
| --- | --- | --- |
| `month` | text | The month the list is for, written YYYY-MM. It is the current month at the school when the request named none. |
| `items` | list of date, written `YYYY-MM-DD` | The days with at least one free hour, earliest first, each day once. Empty when nothing is free in that month. |

### AvailableHours

The free slots of one member of the staff on one day.

| Field | Kind | What it says |
| --- | --- | --- |
| `day` | date, written `YYYY-MM-DD` | The day the list is for. |
| `items` | list of [AvailableSlot](#availableslot) | The free slots, earliest first. Empty when nothing is free on that day. |

### AvailableSlot

A stretch of time that a member of the staff offers for a meeting.

| Field | Kind | What it says |
| --- | --- | --- |
| `starts_at` | date and time with an offset | When the slot starts, with the school's offset. |
| `ends_at` | date and time with an offset | When the slot ends, with the school's offset. |

### Blocked

Automatic logins are paused until an operator resets the block.

A wrong password can lock a guardian's account, so the server stops after the first login
failure that could do that and waits for a person to fix the cause.

| Field | Kind | What it says |
| --- | --- | --- |
| `state` | `"blocked"` |  |
| `cause` | one of `"invalid_credentials"`, `"refused_login"`, `"mfa_required"`, `"action_required_in_portal"`, `"state_unreadable"` | The failure that paused automatic logins. |
| `since` | date and time with an offset | When the block started. |
| `interstitial` | one of `"CambiarPws"`, `"TxtLegales"`, `"OKCuenta"`, `"MatOnline"`, `"Classroom"` or null | The portal page that needs a person, when the cause is a required step. |

### Body

The words of a message, as safe HTML and as plain text.

| Field | Kind | What it says |
| --- | --- | --- |
| `html` | text | The message as HTML that is safe to show. Scripts, styles, forms, frames, and event handlers are gone, and so are classes and inline styles. A link keeps only an `http`, `https`, `mailto`, or `tel` address. An image stays only when the message carries it inline as a PNG, JPEG, GIF, or WebP picture. |
| `text` | text | The message as plain text. A blank line separates paragraphs. A list item starts with `- `, or with its number and a dot in a numbered list, and a list inside a list is indented by two spaces. Table cells in a row are separated by ` \| `. A link shows its address in parentheses after its words. |
| `simplified` | true or false | True when the message was nested too deeply to read as HTML. Then `html` holds only the words of the message, in one paragraph. |

### Capabilities

What the operator switched on for an account.

| Field | Kind | What it says |
| --- | --- | --- |
| `writes` | true or false | Messages and meeting requests may be sent through the outbox. |
| `forms` | true or false | Forms may be answered. This needs writes as well. |
| `restore_unread` | true or false | A message opened through the API is put back to unread at the portal. |

### Child

One child of the signed-in guardian.

| Field | Kind | What it says |
| --- | --- | --- |
| `id` | text | The portal's student id. Most per-child calls use it, and so do URLs. |
| `person_id` | text | The portal's person id for the child. The agenda and the photo use it. |
| `slug` | text | A short name for URLs, made from the first name. The operator can pin it. |
| `name` | text | The full name as the portal shows it. |
| `first_name` | text |  |
| `relation` | text or null | How the portal labels the relation to the guardian, when it shows one. |

### ChildList

| Field | Kind | What it says |
| --- | --- | --- |
| `items` | list of [Child](#child) |  |

### ConnectionCheck

The result of making sure the account has a working portal session.

| Field | Kind | What it says |
| --- | --- | --- |
| `session` | one of `"new"`, `"reused"` | Whether the server had to log in, or the session it had still worked. |
| `child_count` | whole number or null | How many children the login lists. |

### ConnectionReset

The result of lifting a block.

| Field | Kind | What it says |
| --- | --- | --- |
| `was_blocked` | true or false | Whether logins had been paused before the reset. |

### FieldProblem

One thing wrong with the request, and where it was.

| Field | Kind | What it says |
| --- | --- | --- |
| `location` | list of one of text, whole number | Where the problem is, for example ["query", "fresh"]. |
| `message` | text |  |

### Folder

A folder of messages, as the portal lists it.

| Field | Kind | What it says |
| --- | --- | --- |
| `name` | one of `"received"`, `"sent"` | `received` or `sent`. The message routes take this name. |
| `label` | text | The folder's name as the portal shows it, in the school's language. |
| `count` | whole number, at least 0 or null | The number the portal prints next to the folder's name, or null when it prints none. Treat it as a hint. The message list reports the exact total. |

### FolderList

| Field | Kind | What it says |
| --- | --- | --- |
| `items` | list of [Folder](#folder) |  |

### Health

The process is up. This says nothing about the portal.

| Field | Kind | What it says |
| --- | --- | --- |
| `status` | `"ok"` |  |
| `version` | text |  |

### Index

Where things are on this server.

| Field | Kind | What it says |
| --- | --- | --- |
| `name` | text |  |
| `version` | text |  |
| `docs` | text or null | The interactive documentation, or null when it is off. |
| `openapi` | text or null | The OpenAPI document, or null when it is off. |
| `health` | text | The liveness check. |

### LessonSignals

What the school flags on one lesson. A zero or a false means that nothing is flagged.

| Field | Kind | What it says |
| --- | --- | --- |
| `tasks` | whole number, at least 0 | Homework and tasks tied to the lesson. |
| `activities` | whole number, at least 0 | Activities tied to the lesson. |
| `notes` | whole number, at least 0 | Teacher notes tied to the lesson. |
| `tests` | whole number, at least 0 | Tests and quizzes tied to the lesson. |
| `substitution` | true or false | True when a substitute teacher takes the lesson. |

### Link

An address that a message mentions, in a link or in its words.

| Field | Kind | What it says |
| --- | --- | --- |
| `url` | text | The address as the message writes it. |
| `host` | text | The host the address points to, without a leading `www.`. For a mail address, the part after the `@`. |
| `kind` | one of `"email"`, `"video_call"`, `"form"`, `"video"`, `"document"`, `"other"` | What the address is for, judged from its host and its file name. `other` when it is none of the kinds this API knows. |

### LoggedIn

A session is open and the portal answered it recently.

| Field | Kind | What it says |
| --- | --- | --- |
| `state` | `"logged_in"` |  |
| `since` | date and time with an offset | When this session logged in. |
| `last_success_at` | date and time with an offset | When the portal last answered a call. |

### LoggedOut

No session is open. The next request that needs the portal logs in first.

| Field | Kind | What it says |
| --- | --- | --- |
| `state` | `"logged_out"` |  |

### Meeting

A meeting about one child that the portal lists, past, planned, or asked for.

| Field | Kind | What it says |
| --- | --- | --- |
| `id` | text | The portal's meeting id. |
| `state` | one of `"requested"`, `"accepted"`, `"cancelled"`, `"declined"`, `"done"`, `"unknown"` | Where the meeting stands. `requested` waits for an answer, `accepted` is agreed, `cancelled` and `declined` will not take place, and `done` took place. `unknown` means that the portal used a word this server does not know, so read `state_label`. |
| `state_label` | text | The portal's own word for the state, such as `Aceptada`, as it prints it. |
| `starts_at` | date and time with an offset | When the meeting starts, with the school's offset. A meeting held for a whole group can show 00:00 here and put the time of day in `note`. |
| `requested_by` | text or null | Who asked for the meeting, as the portal prints it, or null. |
| `staff` | text or null | The person at the school who is responsible for the meeting, or null. |
| `note` | text or null | The note of the meeting, or null when there is none. |

### MeetingList

The meetings the portal lists for one child, in the order they take place.

| Field | Kind | What it says |
| --- | --- | --- |
| `items` | list of [Meeting](#meeting) |  |

### Message

A message with its words. The fields of its row in the list come first.

| Field | Kind | What it says |
| --- | --- | --- |
| `id` | text | The portal's message id. The detail and attachment routes take it. |
| `read` | true or false or null | Whether the guardian has read the message, or null when the portal's icon is not one this API knows. |
| `institutional` | true or false | True for a message sent in the school's own name. |
| `sender` | text | The sender's name as the portal shows it. |
| `subject` | text |  |
| `received_on` | date, written `YYYY-MM-DD` | The day the portal lists the message under, on the school's calendar. |
| `expires_on` | date, written `YYYY-MM-DD` or null | The last day the portal shows the message, when it has one. |
| `anonymous` | true or false | True when the portal marks the message as anonymous. |
| `category` | text or null | The category the portal files the message under. |
| `has_attachments` | true or false | True when the portal shows a paperclip. |
| `sent_at` | date and time with an offset | When the school sent the message, to the minute, with the school's offset. The list gives only a day, and the time comes from the message itself. |
| `body` | [Body](#body) | The words of the message. |
| `links` | list of [Link](#link) | The addresses in the body, each once. The ones in links come first, then the ones written out in the words. Translations are not searched. |
| `attachments` | list of [Attachment](#attachment) |  |
| `translations` | list of [Translation](#translation) | Other versions of the message, second before third. Empty when there are none. |
| `child_names` | text or null | The names of the children the portal says the message is about, in the one text the portal writes them in, or null when it names none. The portal gives names and no ids, so this API cannot tie them to its list of children. |
| `can_reply` | true or false | Whether the portal offers a reply to this message. |

### MessagePage

One page of the messages in a folder, newest first.

| Field | Kind | What it says |
| --- | --- | --- |
| `items` | list of [MessageSummary](#messagesummary) |  |
| `total` | whole number | How many messages match, counting every page. It counts the messages this server holds, which is fewer than the portal lists when `truncated` is true. |
| `limit` | whole number | The page size that was asked for. |
| `offset` | whole number | How many matching messages come before this page. |
| `next_offset` | whole number or null | The offset to ask for the next page, or null on the last page. |
| `truncated` | true or false | True when the folder is longer than this server reads. The newest messages are here and the oldest are left out. |

### MessageSummary

A message as the portal lists it, without its text.

| Field | Kind | What it says |
| --- | --- | --- |
| `id` | text | The portal's message id. The detail and attachment routes take it. |
| `read` | true or false or null | Whether the guardian has read the message, or null when the portal's icon is not one this API knows. |
| `institutional` | true or false | True for a message sent in the school's own name. |
| `sender` | text | The sender's name as the portal shows it. |
| `subject` | text |  |
| `received_on` | date, written `YYYY-MM-DD` | The day the portal lists the message under, on the school's calendar. |
| `expires_on` | date, written `YYYY-MM-DD` or null | The last day the portal shows the message, when it has one. |
| `anonymous` | true or false | True when the portal marks the message as anonymous. |
| `category` | text or null | The category the portal files the message under. |
| `has_attachments` | true or false | True when the portal shows a paperclip. |

### Problem

An RFC 9457 problem document. Members past `request_id` appear only when they apply.

| Field | Kind | What it says |
| --- | --- | --- |
| `type` | `"about:blank"` | Always about:blank. Use `code`, which is stable, to tell problems apart. |
| `title` | text | The standard name of the HTTP status. |
| `status` | whole number | The HTTP status of the response. |
| `detail` | text | What went wrong and what to do about it, for a person. |
| `code` | text | A stable name for the problem. Branch on this, not on text. |
| `request_id` | text | Quote this when you report a bug. |
| `cause` | one of `"invalid_credentials"`, `"refused_login"`, `"mfa_required"`, `"action_required_in_portal"`, `"state_unreadable"` or null, optional | Why logins are paused, when the account is blocked. |
| `since` | date and time with an offset or null, optional | When logins were paused, when the account is blocked. |
| `interstitial` | one of `"CambiarPws"`, `"TxtLegales"`, `"OKCuenta"`, `"MatOnline"`, `"Classroom"` or null, optional | The portal page that wants a person, in a browser. |
| `reason` | one of `"not_on_allowlist"`, `"never_call"`, `"writes_disabled"`, `"forms_disabled"`, `"unread_restore_disabled"` or null, optional | Which of the operator's switches refused the call. |
| `needed` | one of `"read"`, `"write"`, `"admin"`, `"feed"` or null, optional | The scope the key would need, when it lacks one. |
| `retry_after_seconds` | whole number or null, optional | How long to wait before asking again, when rate limited. |
| `errors` | list of [FieldProblem](#fieldproblem) or null, optional | The parts of the request that are not valid. |

### Readiness

Whether the server can serve requests. It never calls the portal.

| Field | Kind | What it says |
| --- | --- | --- |
| `status` | one of `"ready"`, `"not_ready"` |  |
| `checks` | table of one of `"ok"`, `"failed"` | One entry per thing that was checked. |

### StaffList

| Field | Kind | What it says |
| --- | --- | --- |
| `items` | list of [StaffMember](#staffmember) |  |

### StaffMember

A teacher or other staff member who can meet with the guardian about a child.

| Field | Kind | What it says |
| --- | --- | --- |
| `id` | text | The portal's employee id. Meeting requests use it. |
| `name` | text |  |
| `role` | text or null | The role the portal prints after the name, if any. |

### TrackingCounters

The numbers in the portal's tracking widget for one child.

| Field | Kind | What it says |
| --- | --- | --- |
| `tasks` | whole number, at least 0 | Homework and tasks. |
| `activities` | whole number, at least 0 | Activities. |
| `notes` | whole number, at least 0 | Teacher notes. |
| `tests` | whole number, at least 0 | Tests and quizzes. |
| `incidents` | whole number, at least 0 | Attendance incidents. |

### Translation

The message in another language, when the sender wrote one.

| Field | Kind | What it says |
| --- | --- | --- |
| `slot` | one of `2`, `3` | The portal keeps up to three versions of a message and does not name their languages. The message itself is the first version, so a translation is the second or the third. |
| `subject` | text |  |
| `body` | [Body](#body) |  |
