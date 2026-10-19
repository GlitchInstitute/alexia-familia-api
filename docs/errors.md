# Errors

Every failure comes back as a problem document. A client can branch on a stable `code`, show `detail` to a person, and quote `request_id` when it asks for help. This page lists every code, what it means, and what to do.

## The shape of a problem

A problem document follows [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457). It has the media type `application/problem+json`.

```json
{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "detail": "no child 'nobody' on this account, use a student id or a name from the list of children, and ask for that list with fresh=true if a sibling was added lately",
  "code": "child_not_found",
  "request_id": "766eec589287412d8025af943393c78a"
}
```

| Member | What it holds |
| --- | --- |
| `type` | Always `about:blank`. Use `code` to tell problems apart. |
| `title` | The standard name of the HTTP status. |
| `status` | The HTTP status of the response. |
| `detail` | What went wrong and what to do, in words for a person. |
| `code` | A stable name for the problem. Branch on this and not on `detail`. |
| `request_id` | The id of the request. The response carries it in `X-Request-Id` too, and the access log has it. |

Some problems add a member. A member that does not apply is left out.

| Member | When it appears |
| --- | --- |
| `cause`, `since` | `breaker_open`. Why logins are paused, and since when. |
| `interstitial` | `action_required_in_portal`. The portal page that needs a person. |
| `reason` | `denied`. Which switch of the operator refused the call. |
| `needed` | `insufficient_scope`. The scope the key would need. |
| `retry_after_seconds` | `rate_limited`. How long to wait. The `Retry-After` header says the same. |
| `errors` | `validation_error`. A list with one item for each part of the request that is not valid. An item has a `location` list and a `message`. |

The portal's own words reach `detail` only where a login failed, and a reply that changed shape never reaches a client.

## Who has to act

The status tells you who can fix the problem.

| Status | Who acts |
| --- | --- |
| `4xx` | The caller. The request or the key has to change. A `413` on a file means the file is larger than the operator lets this server carry. |
| `503` | The operator. This account cannot be used until someone acts, for example after a wrong password. |
| `502`, `504` | Nobody on your side. The portal misbehaved or did not answer, so try again later. |
| `500` | The server has a bug. Quote the request id to the operator. |

## When the request or the key is wrong

| Code | Status | What it means | What to do |
| --- | --- | --- | --- |
| `invalid_host` | 400 | The `Host` header names a host that the operator's `allowed_hosts` does not list. The two health checks answer for any host. | Call the server by one of its listed names, or ask the operator to add yours. A proxy has to pass the original `Host` header on. |
| `missing_api_key` | 401 | The request has no key. | Send `Authorization: Bearer <key>`, or `X-API-Key: <key>`. The response carries a `WWW-Authenticate` challenge. |
| `invalid_api_key` | 401 | The key is not known. It may have been revoked or mistyped. | Make a new key with `alexia-api keys create`. |
| `key_not_allowed_in_url` | 403 | A calendar address carries a key that holds more than the `feed` scope. | Send the key in a header, or make a key for the calendar with `alexia-api keys create NAME --scope feed`. |
| `insufficient_scope` | 403 | The key lacks the scope this call needs. `needed` names it. | Use a key with that scope. |
| `rate_limited` | 429 | The key made more requests than `rate_limit_per_minute` allows. | Wait `retry_after_seconds` and try again. Do not poll in a loop. |
| `account_not_found` | 404 | No account has this name, or the key may not use it. | List the accounts with `GET /v1/accounts`. |
| `child_not_found` | 404 | No child on the account matches. | List the children, and use a student id or a slug from the list. Ask for the list with `fresh=true` if a sibling was added lately. |
| `guardian_not_found` | 404 | The portal did not list a guardian for this login, so there is no guardian agenda. | Use the agenda of each child. |
| `staff_not_found` | 404 | The staff list of the child has no such person. | Use an id from the staff list of the same child. Read that list with `fresh=true` if a teacher was added lately. |
| `message_not_found` | 404 | The folder holds no such message. | Use an id from the list of the same folder, and read the list with `fresh=true` if the message arrived lately. |
| `attachment_not_found` | 404 | The message has no such file. | Use an id from the `attachments` of the message. |
| `form_not_found` | 404 | The list of forms holds no such form. | Use an id from the list of forms, and read the list with `fresh=true` if the form arrived lately. |
| `not_found` | 404 | No route answers at this address. | Check the path against the [endpoint reference](endpoints.md). |
| `method_not_allowed` | 405 | The route does not take this method. The `Allow` header lists the ones it takes. | Use one of them. |
| `attachment_too_large` | 413 | A file is larger than the operator's `max_attachment_mib`, so the server did not fetch it. | Ask the operator to raise the limit, or open the message in the portal. |
| `validation_error` | 422 | A parameter is missing or not valid. `errors` says which. | Fix each location that `errors` names. |
| `invalid_window` | 422 | A date range is too long, too far from today, or ends before it starts. A month or a day asked for in the free hours of staff is too far from today. | Ask for a shorter range, or for days that lie within about three years of today. |

## When the account cannot be used

These problems carry `503`. The server cannot use the account until a person acts. Four of them also pause every automatic login, because another try could lock the account. The next section shows how to lift a pause.

| Code | Status | What it means | What to do |
| --- | --- | --- | --- |
| `no_credentials` | 503 | The account has no user name or password configured. | Set the variables or files that `username` and `password` name. |
| `invalid_credentials` | 503 | The portal rejected the user name or the password. This pauses logins. | Correct the login, check it in a browser, and reset the pause. |
| `refused_login` | 503 | The portal refused the login with a message the server does not know. This pauses logins. | Sign in with a browser to see what the portal says, fix the cause, and reset the pause. |
| `mfa_required` | 503 | The account asks for a multifactor PIN, which the server cannot enter. This pauses logins. | Ask the school whether the login can work without that step. |
| `action_required_in_portal` | 503 | The portal wants a step done in a browser, such as accepting a legal notice. `interstitial` names the page. This pauses logins. | Sign in once with a browser and finish the step, then reset the pause. |
| `role_choice_required` | 503 | The login has several roles and the settings name none. | Set `role_id` for the account. |
| `no_role` | 503 | The login has no role. | Ask the school to check the account. |
| `portal_maintenance` | 503 | The portal looks to be in maintenance or down. | Try again later. |
| `breaker_open` | 503 | Logins are paused because an earlier login failed in a way that could lock the account. `cause` says why and `since` says when. | Fix the cause, then reset the pause. |

The `cause` of a pause is one of these.

| Cause | What happened |
| --- | --- |
| `invalid_credentials` | The portal rejected the user name or the password. |
| `refused_login` | The portal refused the login. |
| `mfa_required` | The portal asked for a multifactor PIN. |
| `action_required_in_portal` | The portal asked for a step in a browser. |
| `state_unreadable` | The block file in the state directory could not be read, so the server assumes the worst. Make it readable or reset the pause. |

## When the portal misbehaves

| Code | Status | What it means | What to do |
| --- | --- | --- | --- |
| `transport` | 502 or 504 | The call did not reach the portal or got no answer. A timeout is `504`. Anything else is `502`. | Check that the machine reaches the portal, and try again. |
| `token_invalid` | 502 | The portal said the login token is no longer valid, and a fresh token did not help either. The password was not judged, so logins are not paused. | Try again in a few minutes. |
| `session_expired` | 502 | The portal no longer accepts the session. The server signed in again and the portal still refused. | Try again later. |
| `portal_fault` | 502 | The portal reported a fault of its own. | Try again later. |
| `ws_rejected` | 502 | One of the portal's script services answered with an error status. | Try again later, and report it if it stays. |
| `unexpected_reply` | 502 | The portal sent something that no known shape fits. | Report it with the request id. The portal may have changed. |
| `portal_changed` | 502 | A call came back in a different shape than the server expects. `detail` names the part that changed. | Report it with the request id. The portal probably changed and a reader needs a fix. |

## When the server itself fails

| Code | Status | What it means | What to do |
| --- | --- | --- | --- |
| `internal_error` | 500 | Something went wrong inside the server. | Quote `request_id` to the operator, who can find the request in the log. |
| `denied` | 500 | The server refused one of its own calls, because the call is not on its list of allowed calls or is on its never-call list. This is a bug. | Quote `request_id` to the operator and report it. |

## Codes for features that come later

This version only reads from the portal, and no call takes a request body. These codes belong to calls that send something, and the server defines them now so that clients can plan for them.

| Code | Status | What it means | What to do |
| --- | --- | --- | --- |
| `payload_too_large` | 413 | The request body is larger than the server accepts. | Send less. |
| `denied` | 403 | One of the operator's switches refuses the call. `reason` is `writes_disabled`, `forms_disabled`, or `unread_restore_disabled`. | The operator can turn the switch on. |
| `compose_rejected` | 422 | The portal refused to save or send a message and said why in `detail`. | Change the message as `detail` says. |
| `compose_mismatch` | 502 | The portal's saved copy of a message differs from what was prepared, so nothing was sent. | Prepare the message again. |

## Lift a pause on logins

A pause protects the account, so lift it only after you fix the cause. A reset allows one more login, and a wrong password can lock the account.

```bash
alexia-api accounts list
alexia-api accounts reset marta
```

From a source checkout, put `pixi run` in front of each command. A running server notices the reset by itself.

A key with the `admin` scope can do the same with a request.

```bash
curl -X POST -H "Authorization: Bearer YOUR_KEY" \
  "http://127.0.0.1:8000/v1/accounts/marta/connection/reset"
```

The [troubleshooting guide](troubleshooting.md) shows how to find the cause.
