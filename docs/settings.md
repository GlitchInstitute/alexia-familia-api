# Settings reference

This page comes from the code, so do not edit it by hand. Run `pixi run -e dev docs` to write it again.

Put a setting in `alexia-api.toml`, or set it with an environment variable. A variable wins over the file. The [configuration guide](configuration.md) explains both ways, how to keep passwords out of the file, and how to set up several accounts.

## Settings at the top of the file

| Setting | Variable | Kind | Default | What it does |
| --- | --- | --- | --- | --- |
| `state_dir` | `ALEXIA_API_STATE_DIR` | path | `"state"` | Where the server keeps its few files, such as the API key hashes and the account blocks. A relative path starts at the folder of the configuration file. |
| `timezone` | `ALEXIA_API_TIMEZONE` | text | `"Europe/Madrid"` | The school's time zone name. Times in responses carry this zone's offset. |
| `allow_writes` | `ALEXIA_API_ALLOW_WRITES` | true or false | `false` | Lets API keys with the write scope send messages and meeting requests. |
| `allow_forms` | `ALEXIA_API_ALLOW_FORMS` | true or false | `false` | Lets the server answer forms. This needs allow_writes as well. |
| `restore_unread` | `ALEXIA_API_RESTORE_UNREAD` | true or false | `false` | Puts a message back to unread at the portal after the API opened it, for the case that opening a message marks it read there. Nothing is put back while this is off. |
| `min_spacing_seconds` | `ALEXIA_API_MIN_SPACING_SECONDS` | number | `0.15` | The least number of seconds between two requests to the same portal. A pause keeps the server gentle on the school's portal. It must be at least 0.1 and at most 60. |
| `request_timeout_seconds` | `ALEXIA_API_REQUEST_TIMEOUT_SECONDS` | number | `30` | Seconds to wait for the portal to answer one request. It must be more than 0 and at most 300. |
| `rate_limit_per_minute` | `ALEXIA_API_RATE_LIMIT_PER_MINUTE` | whole number | `120` | How many requests one API key may make each minute. Zero turns it off. It must be at least 0. |
| `max_attachment_mib` | `ALEXIA_API_MAX_ATTACHMENT_MIB` | whole number | `25` | The largest file, in mebibytes, that the server fetches from the portal and hands to a client. A file is held in memory while it travels, so a higher number needs more memory for each download in progress. It must be at least 1 and at most 256. |
| `docs_enabled` | `ALEXIA_API_DOCS_ENABLED` | true or false | `true` | Serves /docs, /redoc, and /openapi.json. The /docs page loads its scripts from a public CDN in your browser. Turn this off when the server is on the internet. |
| `cors_origins` | `ALEXIA_API_CORS_ORIGINS` | list of text | `[]` | Web pages from these origins may call the API in a browser. In a variable, separate the origins with commas. |
| `allowed_hosts` | `ALEXIA_API_ALLOWED_HOSTS` | list of text | `[]` | Answer only requests for these host names, such as api.example.test, or *.example.test for every subdomain. Write the names without https:// and without a port. Empty means any. The two health checks answer for any name, because a platform probes with its own address. In a variable, separate the names with commas. |
| `log_level` | `ALEXIA_API_LOG_LEVEL` | one of debug, info, warning, error | `"info"` | How much the server writes to its log. |
| `log_format` | `ALEXIA_API_LOG_FORMAT` | one of text, json | `"text"` | Plain lines for people, or one JSON object per line. |

## The `accounts.<name>` table

The portal accounts to serve, keyed by a short name used in URLs.

| Setting | Variable | Kind | Default | What it does |
| --- | --- | --- | --- | --- |
| `accounts.<name>.label` | `ALEXIA_API_ACCOUNTS__<NAME>__LABEL` | text | not set | A name for people, such as the guardian's first name. It shows in responses and in the names of the calendars that belong to the whole account. Defaults to the account name. It must be at least 1 character and at most 80 characters. |
| `accounts.<name>.login_url` | `ALEXIA_API_ACCOUNTS__<NAME>__LOGIN_URL` | text | not set | The address of the portal's login page, pasted as is. The server takes the portal address and the school key from it. Use this or portal_url with institution_key. |
| `accounts.<name>.portal_url` | `ALEXIA_API_ACCOUNTS__<NAME>__PORTAL_URL` | text | not set | The portal's web address without a path, for example https://portal.example.test. |
| `accounts.<name>.institution_key` | `ALEXIA_API_ACCOUNTS__<NAME>__INSTITUTION_KEY` | text | not set | The school key, which is the value after key= in the login page's address. It must be at least 1 character. |
| `accounts.<name>.username` | `ALEXIA_API_ACCOUNTS__<NAME>__USERNAME` | text | required | The guardian's portal user name. Write `env:NAME` to read it from an environment variable or `file:/path` to read it from a file. |
| `accounts.<name>.password` | `ALEXIA_API_ACCOUNTS__<NAME>__PASSWORD` | text | required | The guardian's portal password. Write `env:NAME` to read it from an environment variable or `file:/path` to read it from a file, so the config file holds no secret. |
| `accounts.<name>.role_id` | `ALEXIA_API_ACCOUNTS__<NAME>__ROLE_ID` | text | not set | Which role to sign in with when the login has several. Usually not needed. |
| `accounts.<name>.slugs` | `ALEXIA_API_ACCOUNTS__<NAME>__SLUGS` | table of text | `{}` | Pins a child's name in URLs. Each key is a slug and each value is the child's student id, so URLs stay the same when a sibling is added. |

## The `cache` table

How long answers are reused before the portal is asked again. Zero turns the reuse off.

| Setting | Variable | Kind | Default | What it does |
| --- | --- | --- | --- | --- |
| `cache.children` | `ALEXIA_API_CACHE__CHILDREN` | number | `900` | Seconds to reuse the list of children. It must be at least 0. |
| `cache.tracking` | `ALEXIA_API_CACHE__TRACKING` | number | `120` | Seconds to reuse the five tracking counters. It must be at least 0. |
| `cache.staff` | `ALEXIA_API_CACHE__STAFF` | number | `3600` | Seconds to reuse the staff a guardian can meet. It must be at least 0. |
| `cache.folders` | `ALEXIA_API_CACHE__FOLDERS` | number | `300` | Seconds to reuse the list of message folders. It must be at least 0. |
| `cache.messages` | `ALEXIA_API_CACHE__MESSAGES` | number | `120` | Seconds to reuse the list of messages in a folder. It must be at least 0. |
| `cache.message` | `ALEXIA_API_CACHE__MESSAGE` | number | `900` | Seconds to reuse one message with its words, after it was read. It must be at least 0. |
| `cache.agenda` | `ALEXIA_API_CACHE__AGENDA` | number | `600` | Seconds to reuse the agenda of a child or of the guardian for one range. It must be at least 0. |
| `cache.absences` | `ALEXIA_API_CACHE__ABSENCES` | number | `600` | Seconds to reuse the absences the portal lists for a child. It must be at least 0. |
