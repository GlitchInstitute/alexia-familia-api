# Contributing

Thank you for helping. This page takes you from a fresh clone to a pull request. It also lists the few rules that keep a server safe when it talks to a school's system with a parent's login.

## Rules that never bend

1. **No real data in this repository.** Not in code, tests, docs, commit messages, or issues. Use the made-up `5afe0000-...` ids and reserved domains such as `portal.example.test`. A check named `privacy` fails on real-looking GUIDs, emails, and names that a maintainer keeps in a private list.
2. **Reading comes before writing.** Anything that changes something at the school stays behind a switch that is off by default, and it goes through the outbox. The design page explains why.
3. **Be gentle with the portal.** One request at a time for each account, a pause between requests, and no work in the background. Do not add polling.
4. **Never call a delete.** The portal's `Borrar`, `Eliminar`, and `Delete` methods are on a never-call list, and a test scans the source for them.
5. **A change needs a test that fails without it.** Write the test, watch it fail, then make it pass.

## Set up

Install [pixi](https://pixi.sh). It installs Python, every library, and every tool from the lock file, so you need nothing else.

```bash
git clone https://github.com/GlitchInstitute/alexia-familia-api.git
cd alexia-familia-api
pixi run -e dev check
```

The first run downloads the environment, so it takes a few minutes. `check` is the same set of checks that CI runs. When it passes, you are ready.

To try the server without an account, run `pixi run demo`. It starts the API against a made-up school and prints a key and some requests to try.

## Everyday commands

Run these with `pixi run -e dev NAME`.

| Task | What it does |
| --- | --- |
| `test` | Runs the tests. |
| `cov` | Runs the tests with fixed property examples and fails below 90 percent coverage. |
| `lint` | Checks style and common mistakes with ruff. |
| `fmt` | Fixes what ruff can fix and formats the code. |
| `typecheck` | Checks types with mypy in strict mode. |
| `privacy` | Fails when a file or a commit holds real-looking personal data. |
| `workflows` | Checks the GitHub Actions files, and the shell they run, with actionlint. |
| `shell` | Checks the shell scripts with shellcheck. |
| `docs` | Writes the pages that come from the code, such as the endpoint reference and the settings reference. |
| `build` | Builds the wheel and the source archive into `dist/`. |
| `dist-check` | Builds, then checks that the package metadata is valid. |
| `check` | Runs `lint`, `typecheck`, `workflows`, `shell`, `privacy`, `cov`, and `dist-check`. |
| `watch` | Starts the server and reloads it when the code changes. |

The commands that parents use, `serve`, `demo`, `init`, `keys`, `accounts`, `doctor`, and `openapi`, also have a pixi task of the same name. A test keeps the two lists in step. When you add a command, add its task in the same commit.

## How the code is laid out

The code has four layers, and imports point down.

```text
api  ->  services  ->  portal  ->  domain
```

- `domain` holds identifiers, models, errors, and time rules. It does no input or output.
- `portal` is the only code that knows how the portal works. It holds the session, the readers, and the parsers.
- `services` holds the caches, the keys, and everything else a server needs that the portal does not.
- `api` is FastAPI. It checks keys, validates input, and calls one service method for each route.
- `sim` is a fake portal. Tests and the demo use it. It imports only `domain` and the clock, and nothing from `portal`, so a mistake in the client cannot hide behind the same mistake in the fake.

The command line, the demo, the doctor, and a few small modules wrap the layers. They may import any layer, and no layer may import them. `tests/test_layers.py` fails when an import points the wrong way, and the message says which file and which import.

Read [docs/design.md](docs/design.md) before you change how the server talks to the portal or how it handles writes.

Two habits keep the code easy to change.

- Parse portal text once, in a reader, and return a frozen model. Nothing above a reader sees a Spanish field name.
- Make a bad state impossible to write. Use a distinct type for each kind of id, a closed union for each kind of error, and an exhaustive `match` for each one.

## Write a test

- Tests drive the real session and the real routes against the simulator, in the same process. Start from `tests/api/support.py` and `tests/harness.py`.
- One file, `tests/test_end_to_end.py`, does the opposite. It starts the installed `alexia-api demo` as a process of its own and asks it over a real socket, so it covers what a process shows and a test in the same process cannot, such as the command line, the banner, and the signals that end a server.
- A test names a behavior. `test_a_call_without_a_key_is_refused_with_a_challenge` says more than `test_auth_1`.
- Test what a client can see, not how the code gets there. A refactor should not break a test.
- When you add a portal feature, add its route to the simulator first. Then write the reader against the simulator, then the service, then the route.
- Property tests use Hypothesis. The `dev` profile picks new examples each run and remembers failures in `.hypothesis/`. The `ci` profile, which `cov` uses, picks the same examples each run and prints a `@reproduce_failure` line when a test fails. Add that line above the test to replay the failure.
- To run part of the suite, name the files of one directory together. With pytest 9.1, `pytest tests/api/test_meta.py tests/test_clock.py tests/api/test_auth.py` fails with `fixture 'api' not found`, and the same files in the order `tests/api/test_meta.py tests/api/test_auth.py tests/test_clock.py` pass.

## Write code

- Python 3.12 or newer. The code uses the newer syntax for generics and type aliases.
- ruff sets the style, and mypy runs in strict mode. Run `pixi run -e dev fmt` before you commit.
- Write a comment only to say why something looks odd. The name of a function or a variable should say what it does.
- Name things after the domain. `read_agenda` says more than `get_data`.
- Do not catch an exception to hide it. Turn it into one of the errors in `domain.errors`.
- Code that runs inside an account's lock must not ask the same gateway for a turn. The gateway refuses it, because that would wait forever.

## Write docs

Docs are part of the change. A reader should be able to follow a page without help.

- Use short sentences, active voice, and plain words.
- Start each page with what the reader can do after reading it.
- Use sentence-case headings.
- Do not use an em dash. Do not use a colon to join two parts of a sentence. A colon before a list is fine.
- Show a command with its output when the output matters.
- Use made-up names, made-up ids, and `portal.example.test` for the portal.
- Put an answer of the API in a `json` block. A test checks each such block against the answers in the OpenAPI document, so a field that was renamed or left out fails the build. Use `jsonl` or `text` for anything else, such as a log line.

The endpoint reference and the OpenAPI snapshot in `docs/` come from the code. A test fails when they differ, and the message names the command that rewrites them.

## Keep your family's names out

The `privacy` check can also look for the names of your own family, and it never needs the names themselves.

1. For each name, school, or street, take one lower-case word of four letters or more, without accents.
2. Write the SHA-256 hash of the word on a line of a file called `.denylist.sha256` at the top of the repository. Git ignores that file. The command `python -c "import hashlib; print(hashlib.sha256(b'zebra').hexdigest())"` prints the hash of `zebra`.
3. Run `pixi run -e dev privacy`. It fails on any file or commit that holds one of the words. The message names the file and the line, and never the word.

To keep the file elsewhere, set `ALEXIA_API_DENYLIST` to its path. A word of fewer than four letters is not checked.

## Update the lock file

pixi pins every package in `pixi.lock`. Dependabot updates the GitHub Actions and the digest of the Ubuntu base image, but not this file. To refresh it, run `pixi update`, then `pixi run -e dev check`, and commit `pixi.lock` with the change.

## Move pixi or Ubuntu to a newer version

Dependabot leaves both alone, so a maintainer moves them by hand.

The version of pixi is written in the `Dockerfile`, in `ci.yml`, and in `release.yml`, and a test fails when the three differ. Change all of them in one commit. The `Dockerfile` also pins the image by digest. Pull the new image, read its digest with `docker images --digests ghcr.io/prefix-dev/pixi`, and write it after the version as `FROM ghcr.io/prefix-dev/pixi:X.Y.Z@sha256:DIGEST`. Then run `pixi run -e dev check` and `scripts/smoke_docker.sh` on an image built from the change.

The runtime image stays on an Ubuntu release with long term support. Move to the next one when you have a reason, change the tag and the digest in the `Dockerfile`, and run the same two checks.

## Open a pull request

1. Branch from `main`.
2. Make small commits. A commit should build, pass the tests, and do one thing.
3. Start the commit message with a short line that reads as a command, such as `Serve the agenda as calendar files`. Then say in plain sentences what changed and why.
4. Run `pixi run -e dev check`.
5. Fill in the pull request form. Link the issue.

CI runs the same checks on Linux with Python 3.12, 3.13, and 3.14, scans the history for secrets, builds the package, and builds and smoke tests the Docker image. The secret scan is gitleaks, and `.gitleaks.toml` lets it pass a placeholder such as `YOUR_KEY` in the docs. A real key in a commit still fails it.

## Make a release

A maintainer does these steps.

1. Move the entries under `Unreleased` in `CHANGELOG.md` into a new section named `## [X.Y.Z] - YYYY-MM-DD`, and leave an empty `Unreleased` above it.
2. Set `__version__` in `src/alexia_api/__init__.py` and `version` in `pixi.toml` to `X.Y.Z`.
3. Run `pixi run -e dev check`.
4. Run `python scripts/release_notes.py --check vX.Y.Z`. It confirms that the tag, both versions, and the changelog agree.
5. Commit, then push the tag `vX.Y.Z`. The release workflow checks everything again, builds the package, pushes the image to the GitHub container registry, and creates the release with the notes from the changelog.

To check the image before a release, run `scripts/smoke_docker.sh IMAGE`. It starts the demo in a locked-down container and requests every route it suggests.

## Report a security problem

Do not open a public issue. Follow [SECURITY.md](SECURITY.md).
