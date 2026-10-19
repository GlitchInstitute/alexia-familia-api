# alexia-familia-api

A REST API for the Alexia Familia parent portal. You run it on your own computer or server. It signs in to your family's portal account and gives what the school publishes to your own apps, as JSON and as calendar files.

> **This is an unofficial tool.** It has no connection to the makers of Alexia or to any school. It signs in with your own login, the way you do in a browser. Before you use it, check that your school allows automated access to the portal, and stop if the school asks you to.

## What you get

- Every child on your login, with the school's counts of tasks, activities, notes, tests, and incidents.
- The teachers a guardian can meet about each child.
- The agenda of each child and of the guardian, as JSON and as one calendar file for the whole family.
- The messages from the school, with their text, their links, and their files.
- Several children on one login, and several logins on one server, for example both parents.
- A typed API with an OpenAPI description, so you can make a client in any language.
- API keys with scopes, so each app sees only what it needs.

The server reads. It never deletes anything at the school. Messages and text come back in the language the school wrote them, which is Spanish for most schools. Names of fields and routes are in English.

## Try it in two minutes

You need no account. The demo runs against a made-up school.

1. Install [pixi](https://pixi.sh). It installs Python and everything else this project needs.
2. Download the project and start the demo.

```bash
git clone https://github.com/GlitchInstitute/alexia-familia-api.git
cd alexia-familia-api
pixi run demo
```

The demo prints a key, a list of requests to copy, and an address that a calendar app can subscribe to. Open `http://127.0.0.1:8000/docs` to try every request in your browser. Press Authorize and paste the key.

From a terminal, this request lists the made-up children of the made-up account `marta`.

```bash
curl -H "Authorization: Bearer YOUR_KEY" "http://127.0.0.1:8000/v1/accounts/marta/children"
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

## Connect your own account

1. Write a starter file. Paste the address of your school's login page.

   ```bash
   pixi run init --account marta --login-url "https://portal.example.test/ACWeb/LogOn.aspx?key=your-school-key"
   ```

2. Put your portal login in the environment, so that no password is in a file. The command above names the variables `PORTAL_MARTA_USERNAME` and `PORTAL_MARTA_PASSWORD`.

   ```bash
   export PORTAL_MARTA_USERNAME='your user name'
   export PORTAL_MARTA_PASSWORD='your password'
   ```

3. Make a key for your phone or your program. The key appears once, so copy it.

   ```bash
   pixi run keys create phone
   ```

4. Check the setup. This command sends nothing to the school.

   ```bash
   pixi run doctor
   ```

5. Start the server.

   ```bash
   pixi run serve
   ```

A wrong password can lock an account at the school, so the server stops trying after the first refused login and waits for you. `pixi run doctor` and the [troubleshooting guide](docs/troubleshooting.md) say what to do.

## Children and accounts

The portal lists all of a parent's children under one login, so one account in this API holds all of them.

- `/v1/accounts/{account}/children` lists the children of an account.
- `/v1/accounts/{account}/children/{child}/...` holds what belongs to one child, such as tracking, staff, and agenda. `{child}` is the child's id or a short name such as `lucia`.
- `/v1/accounts/{account}/messages` and `/folders` belong to the guardian, because the portal keeps one inbox for each login.

A second parent with a separate login is a second account on the same server. A key can be limited to some accounts, so a key for one parent cannot read the other's. [Children and accounts](docs/children-and-accounts.md) covers several children, two parents, and two schools.

## What works today

| Area | Status |
| --- | --- |
| Accounts, children, tracking counters, staff | Ready |
| Agenda as JSON and as calendar files | Ready |
| Message folders, lists, details, and attachments | Ready |
| API keys, scopes, calendar feed keys, rate limits | Ready |
| Docker image and Compose file | Ready |
| Contacts, meetings, and absences | Planned |
| Forms | Planned |
| Sending messages and meeting requests | Planned, and off until you switch it on |

The [design page](docs/design.md) explains what each planned item will do and why it is built the way it is.

The tests run the code against a simulated school. An earlier client by the same author ran the same calls against a real portal, but this Python code has not run against one yet. The [protocol notes](docs/protocol.md) label every fact as seen, read from the portal's scripts, or guessed. For a first run on a real login, start with `pixi run doctor --online`, which sends no password, and then read one child before you read the rest.

## Safety in short

- The server sends one request at a time for each account, with a pause between requests, and does nothing in the background.
- It keeps no school content on disk. Its few files hold key hashes and the block state of each account.
- Keys are stored as hashes. A key made for a calendar opens nothing but calendars, so it can sit in a web address.
- Passwords come from the environment or from a file. They never appear in a response, an error, or a log.
- The server calls only the portal address in your configuration.

Read [SECURITY.md](SECURITY.md) before you put the server on a network, and report problems in private.

## Run it with Docker

```bash
docker build --tag alexia-familia-api .
docker run --rm --publish 127.0.0.1:8000:8000 alexia-familia-api alexia-api demo --host 0.0.0.0
```

The image runs as a normal user and keeps its files in `/data`. [Compose](compose.yaml) shows a full setup with a configuration file and a volume.

## Learn more

For people who run the server.

- [Getting started](docs/getting-started.md) walks through the demo and a first real account, with a section for Windows.
- [Configuration](docs/configuration.md) explains every setting, with the full list in [settings](docs/settings.md).
- [Authentication](docs/authentication.md) explains keys, scopes, and calendar keys.
- [Children and accounts](docs/children-and-accounts.md) explains several children, two parents, and two schools.
- [Calendars](docs/calendars.md) shows how to subscribe a calendar app.
- [Deployment](docs/deployment.md) covers Docker, a service without Docker, a proxy with https, and what to watch.
- [Troubleshooting](docs/troubleshooting.md) follows the order in which things go wrong.

For people who write software against the API.

- [The API guide](docs/api-guide.md) explains the conventions that every route shares.
- [Endpoints](docs/endpoints.md) lists every route, and [errors](docs/errors.md) lists every error code.

For people who change the code.

- [Design](docs/design.md) explains the choices behind the server.
- [Protocol notes](docs/protocol.md) describe the portal and say how sure each fact is.
- [Contributing](CONTRIBUTING.md) explains how to run the tests and send a change.
- [Changelog](CHANGELOG.md) lists what changed in each release.
- [Security](SECURITY.md) explains how to report a problem and how to run the server safely.

## License

[MIT](LICENSE).
