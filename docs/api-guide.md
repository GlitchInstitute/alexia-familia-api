# API guide

This page explains what every route has in common. The [endpoint reference](endpoints.md) lists each route with its parameters and its answers. A running server also serves `/docs`, where you can try each route in a browser.

The examples talk to the demo, so you can run them as they are. Start it with `pixi run demo`. It prints a key. Keep the key in a variable, and the commands stay short.

```bash
export KEY=afk_the_key_the_demo_printed
```

On Windows, use `curl.exe` and set the variable with `$env:KEY = "..."`. The [getting started guide](getting-started.md#windows) has the details.

## How an address is built

A login at the portal holds all the children of a family, so an address names the login first and the child second.

| Group | Address | What it holds |
| --- | --- | --- |
| Server | `/`, `/healthz`, `/readyz` | Where things are, and whether the server is up. These need no key. |
| Accounts | `/v1/accounts`, `/v1/accounts/{account}` | The portal logins this server holds, and the state of each. |
| Children | `/v1/accounts/{account}/children/{child}/...` | What belongs to one child, such as the tracking counters, the staff, the absences, the meetings, and the agenda. |
| Guardian | `/v1/accounts/{account}/guardian/agenda` | The interviews and school events of the parent or guardian. |
| Messages | `/v1/accounts/{account}/messages` and `/folders` | The inbox. It belongs to the login and not to a child, so it sits under the account. |
| Calendars | `.../agenda.ics` | Calendar files for one child, for the guardian, or for the whole family. |

A few rules hold everywhere.

- Write an address the way the [endpoint reference](endpoints.md) shows it. An address with a trailing slash gets a `307` redirect to the address without it, which costs a second request.
- Every data route reads, and it uses `GET`. The two `POST` routes under `/connection` check or reset the login of an account.
- A route ignores a query parameter that it does not know, so a typo in a parameter does not fail. Check the spelling when an answer is not what you expected.
- A key may be limited to some accounts. A request for an account that the key may not use gets the same `404` as an account that does not exist. A key cannot be used to find out which accounts the server holds.

## Ids and names

| What | Looks like | Where to find it |
| --- | --- | --- |
| Account | `marta` | The name in the settings, or `GET /v1/accounts`. It uses lower case letters, digits, and hyphens. |
| Child | The student id `5afe0000-0000-4000-8000-000000000101`, or the slug `lucia` | `GET /v1/accounts/{account}/children`. A route takes either one, and letter case does not matter. |
| Message | `5afe0000-0000-4000-8000-000000001002` | The `id` in the message list. Letter case does not matter. |
| File of a message | A long text such as `NWFmZTAw...` | The `attachments` of the message. Use it as it is. It is a token that the server makes, and it is not the portal's own id. |

An agenda entry has an id too. It joins the portal's id for the entry and the day with a `|`, as in `<id>|2026-10-19`. The portal gives a lesson the same id every week, so the day is what makes each occurrence different. The id stays the same from one read to the next.

A child has a second id, `person_id`. The server uses it inside calendar files, and most clients can ignore it.

Treat every id as text and compare it as text. The [configuration guide](configuration.md#children-and-their-names-in-urls) explains how slugs are made and how to pin one.

## Dates and times

- A date is written `YYYY-MM-DD`, and it names a day at the school. The school's time zone is the `timezone` setting, which is `Europe/Madrid` unless you change it.
- A moment is a date and time with an offset, such as `2026-10-19T09:00:00+02:00`. The offset follows the school's clock changes, so the same lesson reads `+01:00` in winter. A program that converts a moment to UTC gets the same instant.
- A message has a `received_on` date and, when you read it in full, a `sent_at` moment.
- An agenda entry that lasts all day has `all_day` set to true. Its days run from `starts_at` to `ends_at`.

The agenda routes take `from` and `to`. Both days count, so `from=2026-10-19&to=2026-10-19` asks for one day.

| Rule | Value |
| --- | --- |
| Default range | Today and the six days after it. |
| Longest range | 366 days. |
| Furthest from today | `from` may lie up to 1100 days before or after today. The month and the day of the [free hours](#free-hours-of-the-staff) follow the same rule. |

A range that breaks a rule gets the problem `invalid_window`, and the `detail` says what to change.

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://127.0.0.1:8000/v1/accounts/marta/guardian/agenda?from=2026-10-01&to=2026-12-31"
```

The `kind` parameter keeps some kinds of entries. Repeat it to keep several, as in `kind=lesson&kind=interview`. The kinds are `lesson`, `interview`, `holiday`, and `school_event`.

## Lists and pages

Most lists come whole, wrapped in an object with an `items` list. That holds for the accounts, the children, the staff, the absences, the meetings, and the folders. The agenda also says which days it covers, with `from` and `to`. The free hours of the staff say which month or day they cover, with `month` or `day`.

Only the list of messages comes a page at a time, because an inbox can be long.

| Parameter | What it does |
| --- | --- |
| `folder` | `received` or `sent`. The default is `received`. |
| `unread` | `true` keeps the messages that are not known to be read. `false` keeps the ones that were read. |
| `limit` | The most messages in a page, from 1 to 100. The default is 25. |
| `offset` | How many matching messages to skip. The default is 0. |

The answer says where you are.

```json
{
  "items": [
    {
      "id": "5afe0000-0000-4000-8000-000000001001",
      "read": false,
      "institutional": false,
      "sender": "Ana Muestra Tutora",
      "subject": "Reto de matemáticas",
      "received_on": "2026-10-15",
      "expires_on": null,
      "anonymous": false,
      "category": "Aviso",
      "has_attachments": false
    }
  ],
  "total": 8,
  "limit": 1,
  "offset": 0,
  "next_offset": 1,
  "truncated": false
}
```

| Field | What it means |
| --- | --- |
| `items` | The messages of this page, newest first. |
| `total` | How many messages match, across all pages. |
| `limit`, `offset` | The page that you asked for. |
| `next_offset` | The `offset` of the next page, or `null` on the last page. |
| `truncated` | True when the folder is longer than the server reads, so the oldest messages are missing. |

Follow `next_offset` until it is `null`. Do not add up the page sizes yourself.

The server reads a whole folder from the portal once and keeps it for a short time, so paging through a folder costs the portal a single read. The portal serves 50 messages at a time and the server reads at most 200 such pages. A normal inbox needs a few requests. The first read of a very long folder takes a while, because the server pauses between its requests to the portal.

The `read` field is `true`, `false`, or `null` when the portal does not say. The portal may mark a message as read when it opens, and this server cannot tell whether it does. The `read` field shows the state from the list, which is the state from before you opened the message.

## Absences

`GET /v1/accounts/{account}/children/{child}/absences` lists the absences and the other attendance incidents that the portal records for one child, newest day first. A late arrival sits in the same list, and `incident` says which kind a row is.

```json
{
  "items": [
    {
      "id": "5afe0000-0000-4000-8000-000000007501",
      "occurred_on": "2026-10-14",
      "hour": null,
      "area": "Tutoría",
      "teacher": "Rosa Prueba",
      "incident": "Falta de asistencia",
      "note": null,
      "justifiable": true,
      "justified": false,
      "justification": null,
      "accepted": false
    }
  ]
}
```

| Field | What it means |
| --- | --- |
| `occurred_on` | The day of the incident. |
| `hour`, `area`, `teacher`, `note` | What the portal shows in those columns, or `null` when a column is empty. |
| `incident` | The portal's own words for the kind of incident. |
| `justifiable` | False for an incident that the portal does not let a guardian justify, such as a late arrival. |
| `justified` | Whether a reason was given. It is `null` when the portal's cell was not a clear yes or no. |
| `justification` | The reason that was given, or `null`. |
| `accepted` | Whether the school accepted the reason. It is `null` when the portal's cell was not a clear yes or no. |

The portal's page lists the days from the first day of the current month to today. An older absence can be missing, so an empty list does not prove that a child has none. The server only reads the list, and a guardian justifies an absence in the portal. No real list has been read yet, so the [protocol notes](protocol.md#absences) label the cell formats as read from the portal's script and not as seen.

## Meetings

`GET /v1/accounts/{account}/children/{child}/meetings` lists the meetings that the portal shows for one child, in the order they take place, oldest first. A meeting can be past, planned, or only asked for.

```json
{
  "items": [
    {
      "id": "5afe0000-0000-4000-8000-000000007301",
      "state": "accepted",
      "state_label": "Aceptada",
      "starts_at": "2026-10-20T16:00:00+02:00",
      "requested_by": "Marta Ejemplo",
      "staff": "Ana Muestra Tutora",
      "note": null
    }
  ]
}
```

| Field | What it means |
| --- | --- |
| `state` | Where the meeting stands. It is `requested`, `accepted`, `cancelled`, `declined`, `done`, or `unknown`. |
| `state_label` | The portal's own word for the state, such as `Aceptada`. |
| `starts_at` | When the meeting starts, with the school's offset on that day. |
| `requested_by` | Who asked for the meeting, as the portal prints it, or `null`. |
| `staff` | The person at the school who is responsible for the meeting, or `null`. |
| `note` | The note of the meeting, or `null`. |

Only the word `Aceptada` has been seen on a real list. The server reads the other words from a table that nobody has checked against a real portal. A word that is not in the table gives the state `unknown`, so branch on `state_label` for those and tell the project about the word, so the table can learn it. A meeting that the school holds for a whole group can start at `00:00`, with the time of day in the `note`.

The server only reads the list. A guardian asks for a meeting, answers one, or cancels one in the portal.

## Free hours of the staff

Two routes say when a member of the staff has an hour free for a meeting. Both take a person from the staff list of the same child, so read that list first. An id that is not on it gets a `404` with the code `staff_not_found`, and the server does not ask the portal.

The first route gives the days of one month that have at least one free hour. `month` is written `YYYY-MM`, and the default is the current month at the school.

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://127.0.0.1:8000/v1/accounts/marta/children/mateo/staff/5afe0000-0000-4000-8000-000000000604/availability?month=2026-11"
```

```json
{
  "month": "2026-11",
  "items": [
    "2026-11-03",
    "2026-11-05",
    "2026-11-10",
    "2026-11-12",
    "2026-11-17",
    "2026-11-19",
    "2026-11-24",
    "2026-11-26"
  ]
}
```

The second route gives the free hours of one day, each with a start and an end.

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://127.0.0.1:8000/v1/accounts/marta/children/mateo/staff/5afe0000-0000-4000-8000-000000000604/availability/2026-11-03"
```

```json
{
  "day": "2026-11-03",
  "items": [
    {
      "starts_at": "2026-11-03T15:30:00+01:00",
      "ends_at": "2026-11-03T16:00:00+01:00"
    },
    {
      "starts_at": "2026-11-03T16:00:00+01:00",
      "ends_at": "2026-11-03T16:30:00+01:00"
    }
  ]
}
```

An empty `items` list means that nothing is free. A month or a day that lies more than 1100 days from today gets the problem `invalid_window`, which is the rule that the agenda uses too.

The answer belongs to the person and not to the child, so two children who share a teacher share one stored answer. The server keeps it for a minute by default, because other guardians book hours too, and `fresh=true` reads it again. Which days a school offers is the school's rule and not this server's. The demo offers hours from tomorrow on, and a real school can differ.

This server only reads the hours. A guardian asks for a meeting in the portal.

## How fresh an answer is

The server keeps each answer for a short time, so a calendar app that asks every minute does not make the school's portal work every minute. Two headers say how an answer was found.

| Header | What it says |
| --- | --- |
| `X-Cache` | `hit` when the server had the answer, `miss` when it just read the portal, and `bypass` when `fresh=true` forced a new read. |
| `Age` | How many seconds old the answer is. |

```text
$ curl -si -H "Authorization: Bearer $KEY" "http://127.0.0.1:8000/v1/accounts/marta/children"
HTTP/1.1 200 OK
x-cache: miss
age: 0
...
```

Add `fresh=true` when you know that something changed, such as a message that arrived a moment ago. The server then asks the portal again, but it still keeps its pause between two requests to the portal. Do not use `fresh=true` on a timer, because that defeats the cache and loads the school's system for nothing.

Requests for the same answer at the same moment share one read, and a failed read is never stored. The calendar routes have no `fresh` option, because their address is meant for other software. How long each kind of answer is kept is set in the [`cache` table](settings.md#the-cache-table).

Every answer also carries `Cache-Control: no-store`, so a browser or a proxy does not keep anything on its own. Only the server's own cache counts.

## Errors and request ids

A failure is a problem document with a stable `code`. The [errors page](errors.md) lists every code. A client can follow these rules.

| Status | What a client does |
| --- | --- |
| `401`, `403` | Fix the key. Do not try again with the same key. |
| `404`, `422` | Fix the request. Do not try again unchanged. |
| `429` | Wait the number of seconds in the `Retry-After` header, then try again. The `retry_after_seconds` member says the same. |
| `502`, `504` | The portal failed or did not answer. Try again later, and wait longer each time. |
| `503` | The account cannot be used until the operator acts. Show the `detail` and stop asking. |
| `500` | The server has a bug. Quote the `request_id` to the operator. |

Branch on `code`, and show `detail` to a person. The wording of `detail` can change, and `code` does not.

Every response carries an `X-Request-Id` header. A problem repeats it as `request_id`, and the access log has it. Send your own `X-Request-Id` to follow a request through your own logs. The server uses it when it has 8 to 64 characters from the set of letters, digits, `.`, `_`, `~`, and `-`. Otherwise it makes one.

```bash
curl -H "Authorization: Bearer $KEY" -H "X-Request-Id: check-0001" \
  "http://127.0.0.1:8000/v1/accounts/zoe"
```

```json
{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "detail": "no account named 'zoe' is available to this key",
  "code": "account_not_found",
  "request_id": "check-0001"
}
```

## Rate limits

Each key has its own limit, set by `rate_limit_per_minute`. It is 120 unless you change it, and zero turns it off. The limit belongs to the key and not to an address or an account.

A key can use up a minute's worth of requests at once, and then it gets requests back at an even pace. A request that is refused takes nothing from the key, so asking again does not make the wait longer. A request with a wrong key never uses up the limit of another key.

A refused request gets `429`, the problem `rate_limited`, and a `Retry-After` header. Calendar apps ask now and then, so they stay far below the limit. A program that loops over children and messages may not, so give it its own key and a pause.

## Browsers and CORS

A web page from another origin cannot call the server unless the operator lists that origin in `cors_origins`. Without that setting, the browser's preflight request gets a `405` and the page sees a CORS error.

When an origin is listed, the server allows `GET`, `POST`, and `DELETE`, and it accepts the headers `Authorization`, `X-API-Key`, `Content-Type`, and `X-Request-Id`. A page can read `X-Request-Id`, `X-Cache`, `Age`, and `Retry-After` from an answer. A browser keeps a preflight answer for ten minutes.

A key in a public web page is visible to everyone who opens the page. Use a small program on your own server to call the API, or keep the page private. A calendar key is the only kind that is meant to sit in an address.

## Content types

| Answer | Type |
| --- | --- |
| Data | `application/json`, in UTF-8. |
| A problem | `application/problem+json`. |
| A calendar | `text/calendar; charset=utf-8`. |
| A file of a message | Judged from the first bytes of the file, with `Content-Disposition: attachment`. A web page or a vector picture is never named as one, so a client cannot be made to run a file. |
| `/docs` and `/redoc` | HTML. |

Text from the school stays in the school's language, which is Spanish for most schools. Names of routes, fields, and codes are in English.

The server does not compress its answers. A calendar for a whole family can reach a few hundred kilobytes, so let a reverse proxy compress it. The [deployment guide](deployment.md) shows how.

Every API answer also carries `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and a content security policy that forbids everything. The documentation pages load scripts, so they get no content security policy.

## Calendar files

The three `agenda.ics` routes return calendar files. They take a key in a header like any other route, and they also take a key that holds only the `feed` scope as `?key=`, because a calendar app cannot send a header. The [calendar guide](calendars.md) explains how to subscribe and what each file holds.

## The OpenAPI description

The server describes itself in OpenAPI 3.1.

- A running server serves the description at `/openapi.json`, unless the operator turned `docs_enabled` off.
- `pixi run openapi --output openapi.json` writes it without a running server and without any configuration.
- The file `docs/openapi.json` in this repository is the same description, and a test keeps it current.

Each route has a short name, such as `list_children`, `get_child_agenda`, and `download_attachment`. A client generator uses these names for its methods. Each route also lists the problem statuses that it can return, and its description names the `read`, `feed`, or `admin` scope where a route needs one.

The `v1` in the address is the version of the interface. A new field can appear in an answer at any time, so ignore the fields that you do not know. The [changelog](../CHANGELOG.md) says what changes in each release.

## Short clients

Both programs read the key from the variable `KEY` that you set above. This one lists the children, their counters, and the messages, using only the Python standard library.

```python
import json
import os
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8000"
KEY = os.environ["KEY"]


def get(path: str) -> dict:
    request = Request(BASE + path, headers={"Authorization": f"Bearer {KEY}"})
    with urlopen(request) as response:
        return json.load(response)


for child in get("/v1/accounts/marta/children")["items"]:
    counters = get(f"/v1/accounts/marta/children/{child['slug']}/tracking")
    print(child["first_name"], counters)

offset = 0
while offset is not None:
    page = get(f"/v1/accounts/marta/messages?limit=3&offset={offset}")
    for message in page["items"]:
        print(message["received_on"], message["subject"])
    offset = page["next_offset"]
```

This one needs Node 18 or later. It reads the problem document when a call fails, and it shows the `code` and the `request_id`.

```javascript
const base = "http://127.0.0.1:8000";
const headers = { Authorization: `Bearer ${process.env.KEY}` };

async function get(path) {
  const response = await fetch(base + path, { headers });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(`${body.code}: ${body.detail} (request ${body.request_id})`);
  }
  return body;
}

const { items: children } = await get("/v1/accounts/marta/children");
for (const child of children) {
  const counters = await get(`/v1/accounts/marta/children/${child.slug}/tracking`);
  console.log(child.first_name, counters);
}
```

Save it as `client.mjs`, because the top-level `await` needs a module.

## Where to go next

- The [authentication guide](authentication.md) explains keys, scopes, and calendar keys.
- The [children and accounts guide](children-and-accounts.md) explains how one server holds several children and several logins.
- The [errors page](errors.md) lists every problem code.
