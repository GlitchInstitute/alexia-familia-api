# Calendars

A calendar app can subscribe to the school agenda, so lessons, interviews, and school events show next to the rest of your day. The server turns the agenda into a calendar file at a web address, and the app reads that address again from time to time. A subscribed calendar is read-only. Nothing you do in the app changes anything at the school.

This page shows which calendars exist, how to subscribe, what each one holds, and what to check when one misbehaves. The last section is for people who write software.

## Pick a calendar

Each account has three calendars.

| Calendar | Address | What it holds | Name in the app |
| --- | --- | --- | --- |
| The family | `/v1/accounts/marta/agenda.ics` | The lessons and school events of every child, and the guardian's interviews, in one file. | `Marta family school calendar` |
| One child | `/v1/accounts/marta/children/lucia/agenda.ics` | The lessons, school events, and holidays of that child. | `Lucía school calendar` |
| The guardian | `/v1/accounts/marta/guardian/agenda.ics` | The interviews with the school and the school events that the portal shows the guardian. | `Marta school meetings` |

The child in the address is the child's slug or student id. The [configuration guide](configuration.md#children-and-their-names-in-urls) explains slugs. `Lucía` is the child's first name. `Marta` is the `label` of the account, which is the account name unless you set a label in the [account settings](settings.md#the-accountsname-table). Choose a label that reads well in front of "school meetings", such as the guardian's first name.

Subscribe to the family calendar when you want everything in one place. In it, each entry of a child starts with the child's first name, as in `Lucía: Matemáticas`. Two children who share a first name also get their slugs, as in `Ana (ana): Música` and `Ana (ana-2): Música`. An entry that the whole school shares, such as a holiday, appears once and has no name in front.

Subscribe to one calendar for each child when each child needs a colour of their own. Do not subscribe to the family calendar and to a smaller one as well, or every entry shows twice.

## Make a key and an address

A calendar app cannot send a header, so the key goes into the address. Only a key that holds nothing but the `feed` scope may travel there, so make one for calendars.

```bash
pixi run keys create calendar --scope feed --account marta
```

The command shows the key once. Put it after `?key=` to make the address.

```text
https://alexia.example.test/v1/accounts/marta/agenda.ics?key=afk_...
```

Replace `alexia.example.test` with the name of your server. On the computer that runs the server, the address starts with `http://127.0.0.1:8000`. The [deployment guide](deployment.md#put-a-proxy-with-https-in-front) shows how to give the server a name and `https`.

Open the address with `curl` before you give it to an app. Put it in quotes, because a shell cuts an address at the first `&`.

```bash
curl -i "http://127.0.0.1:8000/v1/accounts/marta/agenda.ics?key=$KEY"
```

You should see `200 OK`, the header `content-type: text/calendar; charset=utf-8`, and a body that starts with `BEGIN:VCALENDAR`. Anything else is a problem that names its own cause. The [errors page](errors.md) explains each code.

## Subscribe

Every calendar app can add a calendar from an address, and each one words it differently. Look for "From URL", "Subscribe to calendar", "Add subscribed calendar", or "On the network". Paste the whole address, with `?key=` and the key.

| App | Where to look | Worth knowing |
| --- | --- | --- |
| Google Calendar | On the website, open Other calendars, press the plus sign, and choose From URL. | Google reads the address from its own servers, so the address has to work from the internet. Google refreshes when it likes, which can take many hours, and you cannot ask it to refresh sooner. |
| Apple Calendar on a Mac | File, then New Calendar Subscription. | You choose how often it refreshes. |
| Apple Calendar on an iPhone or iPad | Settings, Calendar, Accounts, Add Account, Other, and Add Subscribed Calendar. | The path changes between versions of iOS. |
| Outlook on the web | Add calendar, then Subscribe from web. | A calendar app in the cloud reads the address from the provider's servers, as Google does. |
| Thunderbird | New Calendar, On the Network, and then the iCalendar (ICS) format. | It reads the address from your own computer, so a private address works. |

Menu names change between versions, so treat the table as a hint.

Which address works depends on who reads it.

| Where the server runs | Address | Apps that can read it |
| --- | --- | --- |
| On the computer you are using | `http://127.0.0.1:8000/...` | Apps on that computer. This suits the demo. |
| On your home network | `http://192.168.1.20:8000/...` | Apps that run on a device inside the network and read the address themselves. An app in the cloud cannot reach it, and some apps refuse plain `http`. |
| On the internet, with a name and `https` | `https://alexia.example.test/...` | Every app. Use this for Google Calendar. |

## What a calendar holds

- A lesson is a timed entry with a start and an end. Its title is the subject as the school writes it. Its description names the teacher and what the school flagged, in plain sentences, such as `Teacher Rosa Prueba.`, `The school flagged 2 tasks and 1 test.`, and `A substitute teacher takes this lesson.` The sentences that the server adds are in English. The school's own words stay as written.
- An interview with the school is a timed entry in the guardian calendar and in the family calendar.
- A school event is a timed entry, or an all-day entry when it lasts the whole day.
- A holiday or any other all-day entry shows as free time, so it does not block your day. An entry that lasts several days shows on each of them.
- Control characters, invisible characters, and runs of spaces in a title are removed, so a title cannot change what the app shows.

Every timed entry is written as one moment in UTC. Your app shows it in the time zone of your device, so a lesson at nine stays at nine on both sides of a clock change. An all-day entry is a whole day at the school, in the zone that the `timezone` setting names.

A calendar reaches back and ahead from today at the school. Lessons stop sooner than the rest, because the school's timetable for the far future is a guess that holidays and changes have not reached.

| What | Default | Query option | Allowed values |
| --- | --- | --- | --- |
| How far back the calendar reaches | 14 days | `back` | 0 to 366 |
| How far ahead it reaches | 180 days | `ahead` | 0 to 366 |
| How far ahead lessons are listed | 90 days | `lessons_ahead` | 0 to 366 |

The guardian calendar has no lessons, so it takes `back` and `ahead` only.

## Change what a calendar shows

Add the options to the address, after the key.

```text
https://alexia.example.test/v1/accounts/marta/agenda.ics?key=afk_...&back=0&ahead=60&lessons_ahead=30
```

An app that already subscribed keeps the old address, so change the address in the app. A value outside the allowed range gets the problem `validation_error`.

## How fresh a calendar is

A change at the school reaches your app in three steps.

1. The server keeps each agenda it read for 10 minutes. The [`cache.agenda` setting](settings.md#the-cache-table) changes that time.
2. The file asks the app to refresh every hour. An app treats this as a hint, and some ignore it.
3. The app reads the address on its own schedule. This is the slowest step, and the server cannot change it.

The first read after the stored agendas expire asks the portal for the list of children when it is not stored, for each child, and for the guardian. A family of two children takes a few seconds. Reads in the next 10 minutes answer at once. Give a reverse proxy a read timeout of a minute or more, as the [deployment guide](deployment.md#timeouts) shows.

Calendar routes have no `fresh` option, because their address is meant for other software.

## When the portal cannot be read

The server never answers with a shorter calendar. When the portal fails, the answer is a problem such as `502`, `503`, or `504`, and a calendar app keeps the entries it had and tries again later. The family calendar is all or nothing for the same reason. When one child's agenda cannot be read, the whole file fails, so an app does not take the missing entries for entries that the school removed.

A pause on logins, for example after a wrong password, makes every calendar answer `503` with the code `breaker_open` until the operator lifts it. The [errors page](errors.md#lift-a-pause-on-logins) shows how.

## Share an address safely

An address with a key in it is a secret. It ends up in the app's settings, in the logs of every proxy on the way, and, for Google and Outlook on the web, on the provider's servers. The server's own log shows the route and never the query string, so the key does not reach it.

- Use `https`, so that the key does not travel in plain text.
- A calendar key opens calendars and nothing else. It cannot read messages or files, and it cannot change anything.
- A leaked address still shows the first names of the children, their lessons, and their teachers until you revoke the key.
- A key opens every calendar of its accounts. You can limit a key to some accounts, and you cannot limit it to one child. Give an address only to people you would trust with all the children of that account.
- Give each person or app its own key, so you can revoke one without the others.

```bash
pixi run keys list
pixi run keys revoke calendar
```

The [authentication guide](authentication.md#calendar-keys) explains calendar keys in full.

## When a calendar does not work

| You see | Why | What to do |
| --- | --- | --- |
| The app cannot read the address, or the calendar stays empty | The address does not work as it stands. | Open it with `curl -i`, as shown above, and read the problem. |
| `missing_api_key` or `invalid_api_key` | The key is missing, mistyped, or revoked. | Check that the address holds `?key=` and the whole key, with no space or quote. |
| `key_not_allowed_in_url` | The key holds more than the `feed` scope. | Make a key with `--scope feed` for calendars. |
| `account_not_found` | The account name is wrong, or the key may not use it. | Check the name against `GET /v1/accounts`, and make a key for that account. |
| `child_not_found` | No child matches the slug or the student id. | List the children and copy a slug. A new sibling shows up after `children?fresh=true`. |
| `guardian_not_found` | The portal does not list a guardian for this login. | Use the family calendar or the calendar of a child. |
| `invalid_host` | The server answers only to the names in `allowed_hosts`. | Use one of those names, or add yours. |
| The address works in a browser and not in Google or Outlook on the web | The provider reads the address from its own servers, and they cannot reach yours. | Give the server a public name and `https`, as the [deployment guide](deployment.md) shows. |
| An entry is an hour off | The time zone of the device is wrong. | Set the zone of the device. The file holds each time as one moment in UTC. |
| Every entry shows twice | You subscribed to the family calendar and to a smaller one, or you subscribed twice. | Remove one of them. |
| Lessons stop after about three months | Lessons are listed 90 days ahead. | Add `lessons_ahead` to the address, up to 366. |
| An entry that the school removed is still there | The app has not refreshed yet. | Wait for its next refresh, or refresh by hand where the app allows it. |
| The name reads `family family school calendar` | The account has no label, so its name stands in front. | Set `label` in the account settings. |

The [troubleshooting guide](troubleshooting.md#a-calendar-app-shows-old-events-or-none) lists more. The project tested these files with software libraries and not with every calendar app. If an app shows something odd, open an issue and name the app and its version.

## For people who write software

The three routes return an iCalendar file. They take the key in a header like any other route, and they take a `feed` key as `?key=`. The [endpoint reference](endpoints.md) lists their parameters and problems.

```text
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//alexia-familia-api//School calendar//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
X-WR-CALNAME:Lucía school calendar
REFRESH-INTERVAL;VALUE=DURATION:PT1H
X-PUBLISHED-TTL:PT1H
X-WR-TIMEZONE:Europe/Madrid
BEGIN:VEVENT
SUMMARY:Educación Física
DTSTART:20261005T070000Z
DTEND:20261005T074500Z
DTSTAMP:20261019T035226Z
UID:5afe0000-0000-4000-8000-000000000201.5afe0000-0000-4000-8000-000000007
 110|2026-10-05@alexia-familia-api
DESCRIPTION:Teacher Rosa Prueba.
END:VEVENT
```

This is real output from the demo, cut after the first entry. These rules hold for every file.

- The media type is `text/calendar; charset=utf-8`. Lines end with CRLF, fold at 75 octets, and use UTF-8.
- Each entry is one `VEVENT`, sorted by start. A timed entry has `DTSTART` and `DTEND` in UTC. An entry with no length has no `DTEND`.
- An all-day entry has `DTSTART;VALUE=DATE` and an exclusive `DTEND;VALUE=DATE`, which is the day after the last day, and `TRANSP:TRANSPARENT`.
- The file holds no `VTIMEZONE` and no `TZID`. Readers differ in how they read zone rules, and one reader put every summer lesson an hour off when the file carried them. A moment in UTC needs no rules. `X-WR-TIMEZONE` names the home zone of the calendar as a hint.
- The `UID` is the id of the person, a dot, and the id of the entry, then `@alexia-familia-api`. It does not change from one fetch to the next, so an app updates an entry in place. An entry that several people share uses the account name in place of a person's id.
- `DTSTAMP` is the time at which the server made the file, so it changes on every fetch while the entry does not. The file has no `SEQUENCE` and no `LAST-MODIFIED`.
- The file asks for a refresh every hour with `REFRESH-INTERVAL` and `X-PUBLISHED-TTL`.
- A title, a name, and a teacher go through the same cleaning, so none of them can add a property or an entry to the file.

Two other readers, the Python libraries `ical` and `vobject`, read the demo's calendars and found the same entries and times as the JSON agenda. The server's own tests read each file back with `icalendar`.
