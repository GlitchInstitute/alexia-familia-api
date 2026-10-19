# Children and accounts

The server works with two levels, accounts and children. You write accounts in the settings file, and the server finds the children by itself. This page shows how to set up one parent with several children, two parents, and two schools, and how the server keeps them apart.

## The two levels

| Level | What it is | Where it lives | Example |
| --- | --- | --- | --- |
| Account | One portal login, which means one guardian at one school. | The settings file. You choose its name. | `marta` |
| Child | A student that the login can see. | The portal. The server reads the list. | `lucia` |

Every address that reaches into the school starts with an account, as in `/v1/accounts/marta/children/lucia/agenda`. You never configure a child. When the school adds a sibling to your login, the child shows up in the list.

Some data belongs to a child and some belongs to the login.

| Belongs to a child | Belongs to the account |
| --- | --- |
| The tracking counters, the staff a guardian can meet, the agenda, and the child's calendar. | The messages, the message folders, the guardian's own agenda, the connection to the portal, and the family calendar. |

A message belongs to the guardian, so the server does not sort messages by child.

## One parent with several children

One login that sees several children needs one account. Siblings are not separate accounts.

```toml
[accounts.marta]
login_url = "https://portal.example.test/ACWeb/LogOn.aspx?key=your-school-key"
username = "env:PORTAL_MARTA_USERNAME"
password = "env:PORTAL_MARTA_PASSWORD"
```

List the children, then use a child's `slug` or `id` in an address.

```bash
curl -H "Authorization: Bearer $KEY" "http://127.0.0.1:8000/v1/accounts/marta/children"
```

```json
{
  "items": [
    {
      "id": "5afe0000-0000-4000-8000-000000000101",
      "person_id": "5afe0000-0000-4000-8000-000000000201",
      "slug": "lucia",
      "name": "Lucía Ejemplo Muestra",
      "first_name": "Lucía",
      "relation": "Hija"
    },
    {
      "id": "5afe0000-0000-4000-8000-000000000102",
      "person_id": "5afe0000-0000-4000-8000-000000000202",
      "slug": "mateo",
      "name": "Mateo Ejemplo Muestra",
      "first_name": "Mateo",
      "relation": "Hijo"
    }
  ]
}
```

These are the made-up children of the demo. `id` is the student id, `slug` is a short name for addresses, and `person_id` is a second id that the server uses inside calendar files.

A short script can visit every child. This one works against the demo, and it needs `jq`.

```bash
KEY=your-key
BASE=http://127.0.0.1:8000

for child in $(curl -s -H "Authorization: Bearer $KEY" "$BASE/v1/accounts/marta/children" | jq -r '.items[].slug'); do
  printf '%s ' "$child"
  curl -s -H "Authorization: Bearer $KEY" "$BASE/v1/accounts/marta/children/$child/tracking" | jq -c .
done
```

```text
lucia {"tasks":3,"activities":1,"notes":0,"tests":2,"incidents":0}
mateo {"tasks":1,"activities":0,"notes":2,"tests":0,"incidents":1}
```

To put all the children in your calendar app, subscribe to the family calendar, which holds every child in one file. The [calendar guide](calendars.md) shows how.

## Names in addresses

A child has two names for addresses, the slug and the student id. Both work in every address.

- The slug is easy to read. The server makes it from the first name in lower case, with letters, digits, and hyphens, so `Ana Belén` becomes `ana-belen`.
- Two children with the same first name get `-2`, `-3`, and so on. The child with the smallest student id keeps the plain name.
- The student id never changes. Use it in software that must not break.

A slug can change when a sibling joins and shares a first name. Pin a slug to a student id when other software depends on an address.

```toml
[accounts.marta.slugs]
lucia = "5afe0000-0000-4000-8000-000000000101"
```

A pin keeps its slug exactly as written, and the other children work around it. A pin for a child that the portal no longer lists is ignored. The [configuration guide](configuration.md#children-and-their-names-in-urls) has the full rules.

## Two parents

When both parents have a login at the school, give each login its own account. Each parent then gets their own messages and their own interviews with the school.

```toml
[accounts.marta]
label = "Marta"
login_url = "https://portal.example.test/ACWeb/LogOn.aspx?key=your-school-key"
username = "env:PORTAL_MARTA_USERNAME"
password = "env:PORTAL_MARTA_PASSWORD"

[accounts.pablo]
label = "Pablo"
login_url = "https://portal.example.test/ACWeb/LogOn.aspx?key=your-school-key"
username = "env:PORTAL_PABLO_USERNAME"
password = "env:PORTAL_PABLO_PASSWORD"
```

To add a second account to a file that exists, print its block and paste it at the end. This command writes nothing.

```bash
pixi run init --print --account pablo --login-url "https://portal.example.test/ACWeb/LogOn.aspx?key=your-school-key"
```

Copy everything from `[accounts.pablo]` to the end, and set the two variables for the new login. The server reads its settings when it starts, so restart it. A new key works at once, without a restart.

The server never merges accounts. When both logins show the same child, the child appears under both accounts. For that reason, subscribe to the family calendar of one account for the shared children, or every lesson shows twice. Subscribe to the guardian calendar of each account, because each parent's interviews differ.

Each account has its own session, its own cache, and its own pause on logins. A wrong password on one account pauses that account and leaves the other one running.

## Two schools

Children at two schools need two accounts, because an account is a login at one portal. Give the second account the address of the other portal.

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

The `timezone` setting applies to the whole server. Two schools in different time zones need two servers.

## See what the server holds

```bash
pixi run accounts list
```

```text
ACCOUNT  PORTAL                     LOGINS
marta    portal.example.test        allowed
pablo    other-portal.example.test  allowed
```

The `LOGINS` column says `allowed`, or `paused` with the cause when a failure paused the account. The command reads the settings and the state folder, and it does not call the portal.

`GET /v1/accounts` gives the same accounts, and it also says how many children each one has. `child_count` is `null` until the server has read the children of that account once.

```bash
curl -H "Authorization: Bearer $KEY" "http://127.0.0.1:8000/v1/accounts"
```

A script that visits every account and child can nest two loops.

```bash
AUTH="Authorization: Bearer $KEY"

for account in $(curl -s -H "$AUTH" "$BASE/v1/accounts" | jq -r '.items[].id'); do
  for child in $(curl -s -H "$AUTH" "$BASE/v1/accounts/$account/children" | jq -r '.items[].slug'); do
    printf '%s/%s ' "$account" "$child"
    curl -s -H "$AUTH" "$BASE/v1/accounts/$account/children/$child/tracking" | jq -c .
  done
done
```

```text
marta/lucia {"tasks":3,"activities":1,"notes":0,"tests":2,"incidents":0}
marta/mateo {"tasks":1,"activities":0,"notes":2,"tests":0,"incidents":1}
pablo/hugo {"tasks":5,"activities":2,"notes":1,"tests":1,"incidents":0}
pablo/alba {"tasks":0,"activities":3,"notes":0,"tests":0,"incidents":2}
```

## Who may see what

A key may use all accounts or only some. This is how you give each parent their own key.

```bash
pixi run keys create marta-phone --account marta
pixi run keys create pablo-phone --account pablo
pixi run keys create both-calendar --scope feed --account marta --account pablo
```

A key limited to `marta` sees only `marta` in the list of accounts. A request for another account gets the same `account_not_found` as for an account that does not exist. The [authentication guide](authentication.md#accounts-a-key-may-use) has the details.

A key cannot be limited to one child. A key that opens an account opens every child of that account. Give a key to people you would trust with all the children of that login.

## When the children change

| What happened | What you see | What to do |
| --- | --- | --- |
| The school adds a sibling to your login. | The child shows up after the server reads the list again, which takes up to 15 minutes. | Ask for `children?fresh=true` to see it at once. Pin the slugs that other software uses. |
| A new sibling shares a first name with a child you have. | The slug of one child can change, for example from `ana` to `ana-2`. | Pin slugs to student ids, and update software that used the old slug. |
| A child leaves the school. | After the server reads the list again, the child's own calendar answers `child_not_found` and the family calendar stops listing the child. | Remove the child's pin from the settings. This is optional, because a pin for a missing child is ignored. |
| You add an account. | Its children and calendars appear after a restart. | Make a key for it, or use a key that may use every account. |

## How requests for children run

The portal keeps one open child for each login, so the server lets one account do one thing at a time. A read for one child waits while another read for the same account runs. A script that visits five children makes five reads in a row, and the server keeps each answer for a while, so a second visit is quick. Different accounts do not wait for each other.

## Run the server for other families

Your passwords stay on the server that you run, so run it for your own family, or for people who trust you with their logins. Another family can run its own copy with its own login, which keeps each login in one place. The [deployment guide](deployment.md) shows how to run the server in a container or as a service.
