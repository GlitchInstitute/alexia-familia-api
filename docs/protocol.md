# Portal protocol notes

These notes describe how the school portal works, as far as this project knows it. They are for people who fix a reader after the portal changes. People who run the server or call the API do not need them.

The portal is a commercial product, and its vendor publishes no documentation for the calls below. The facts come from an earlier client's runs against a real portal and from reading the pages and scripts that the portal sends to every signed-in guardian. Every call here is one that the portal's own pages make. This project is not affiliated with the vendor or with any school.

## How sure each fact is

Each fact has one of three labels.

| Label | Meaning |
| --- | --- |
| Seen | An earlier client by the same author ran the call against a real school portal and recorded the answer. |
| Read | The code follows the portal's own scripts or markup. Nobody has seen the path run. |
| Guessed | The code assumes it. The text says what happens when the guess is wrong. |

One limit outweighs the labels. The Python code in this repository has not run against a real portal. The earlier client was written in TypeScript, and the simulator here copies the shapes that client recorded. A passing test shows that the code and the simulator agree. It does not show that the portal agrees.

Start a first run on a real portal with `alexia-api doctor --online`, which opens the login page and sends no password. Then read one child before you read the rest.

## Rules the client follows

- One request is in flight for each account, because the portal keeps state for each session. See [session state](#session-state).
- Every script call is a row in the allowlist in `portal/allowlist.py`, and a call that is not in the table cannot be sent. Method names that start with `Borrar`, `Eliminar`, or `Delete` are refused, and so are `CarpetaBorrada` and `MarcarComunicadoLeidoBadge`.
- Every call in the table reads. A row marked as a write is refused until the operator turns writes on, and the table has no such row yet.
- The password goes out once for each login. The only retry is for a stale token, which the portal answers before it looks at the password.
- A refusal that can lock the account stops every later login until a person lifts the block. See [errors.md](errors.md#lift-a-pause-on-logins).
- Script calls, page reads, and feeds do not follow redirects, because the portal's own pages never redirect a signed-in guardian and a redirect to the login page means the session ended. The sign-in reads follow redirects on the portal's own origin, up to five hops, and refuse any other.
- At least 150 ms passes between request starts. See [politeness](design.md#politeness) for the rest of the manners.
- A response over 8 MiB is refused, and a file download is held to the size limit the operator sets.

## Addresses

Every path starts at `/ACWeb/` on the school's host. The `key` in the login address names the school on a host that serves several, and only the login page needs it.

| What | Path | Label |
| --- | --- | --- |
| Login page | `/ACWeb/LogOn.aspx?key=<school key>` | Seen |
| Home page | The `RutaHome` of the sign-in, which is `/ACWeb/paginas/Home/HomeMetro.aspx` | Seen |
| Agenda page | `/ACWeb/paginas/Agenda/PaginaAgenda.aspx` | Seen |
| Agenda feed | `/ACWeb/controladores/ControladorAgenda.ashx` | Seen |
| Message list | `/ACWeb/paginas/Comunicacion/Comunicados.aspx` | Seen |
| One message | `/ACWeb/paginas/Comunicacion/Comunicado.aspx` | Seen |
| File download | `/ACWeb/Controladores/ControladorRepositorio.ashx` | Seen |
| Absences page and its grid feed | `/ACWeb/paginas/incidencias/Justificar.aspx` | Seen |
| Meetings page and its grid feed | `/ACWeb/paginas/Grids/Entrevistas.aspx` | Seen |
| Script services | `/ACWeb/WS_Data/<Service>.asmx/<Method>` | Seen |

The portal uses GUID strings for people, messages, and roles. A child has two of them, the student id and the person id, and they are different values. The student id feeds the tracking widget and the staff list. The person id feeds the agenda and the photo. The guardian has a person id as well. This project gives each kind its own type, so passing one where the other belongs fails type checking.

## Script calls

A script call is a JSON `POST` to `/ACWeb/WS_Data/<Service>.asmx/<Method>`. The body is a JSON object whose names are the portal's own. The answer is `{"d": <value>}`. The client sends the headers that the portal's own scripts send.

Request models refuse names they do not know, so a typo cannot reach the portal. Reply models ignore names they do not know and refuse a wrong type. A portal that starts to send a number as text fails loudly as `portal_changed` and does not turn into wrong data.

| Call | What it does | Parameters | Reply | Label |
| --- | --- | --- | --- | --- |
| `WSLogOn.Validar` | Checks the password | `token`, `nickname`, `password` | Empty text when accepted, otherwise the refusal sentence | Seen |
| `WSLogOn.GetRoles` | Lists the roles of the login | `token` | `OK` with `Identificador` entries, or `Error`, `multifactor`, `Ruta` | Seen with one role, Read for the rest |
| `WSLogOn.ValidarRol` | Picks a role and ends the sign-in | `token`, `idRol`, `evaluarMultifactor` | `OK`, `RutaHome`, `OKCuenta`, `Error`, and the interstitial fields | Seen for a plain sign-in |
| `WSSesion.CheckSession` | Probes the session | `contador` | `IsOk` and sometimes `Mensaje` | Seen |
| `WSHome.GetWPSeguimiento` | The tracking widget of one child | `idAlumno` | Five HTML fragments named `tareas`, `actividades`, `anotaciones`, `controles`, `incidencias` | Seen |
| `WSReuniones.GetEmpleadosByHijo` | The staff a guardian can meet about one child | `guidHijo` | A list of `Valor` and `Texto` | Seen |
| `WSReuniones.GetFechasDisponibles` | The days of one month on which a person has a free hour | `guidEmpleado`, `mes`, `anyo` | `{horarios: ["YYYY,M,D", ...]}` with one text for each free hour, or `{}` when nothing is free | Seen |
| `WSReuniones.GetHorasByFecha` | The free hours of one person on one day | `guidEmpleado`, `fecha` as ISO text | `{horas: ["HH:MM-HH:MM", ...]}`, or `{}` when nothing is free | Seen |
| `WSComunicados.GetArbolCarpetasJSON` | The folder tree | `IsAutorizacion` | `nodos`, which is JSON inside the JSON | Seen |
| `WSComunicados.CarpetaSeleccionada` | Makes the portal list one folder | `idCarpeta`, `IsAutorizacion`, `TextoBusqueda` | An object that the client ignores | Seen |
| `WSComunicados.GetDatosPaginaComunicado` | The data of the message that is open | None | The message fields | Seen |

### When a call fails

| What the portal sends | What it means | The client says | Label |
| --- | --- | --- | --- |
| HTTP 401 with `{"Message":"Error al procesar la solicitud.","StackTrace":"","ExceptionType":""}` | The session ended | `session_expired` | Seen |
| HTTP 302 to `LogOn.aspx?ReturnUrl=<path>` | The session ended | `session_expired` | Seen |
| HTTP 200 with the login page where JSON belongs | The session ended | `session_expired` | Read |
| HTTP 500 with the same generic body | A parameter is wrong, and the session is fine | `ws_rejected` | Seen |
| HTTP 200 with a small page that posts to `PaginaError.aspx` | The call failed | `ws_rejected` | Read |
| HTTP 502, 503, or 504 | The portal is down or in maintenance | `portal_maintenance` | Guessed |
| A reply that is not the shape in `portal/wire.py` | The portal changed | `portal_changed` | Not applicable |

The gateway answers `session_expired` once by logging in again and repeating the recipe. A second `session_expired` goes to the caller. Any other status that is not 200 is `ws_rejected`. The maintenance statuses are a guess about what a school does while it updates the portal. If a real portal answers another way, the fix is one constant in `portal/ws.py`.

## Signing in

A sign-in is one page read and three script calls, then the home page.

1. Read `LogOn.aspx?key=<school key>`. The page holds a hidden input with the id `Token`. A page with no token and the word `mantenimiento` or `maintenance` counts as maintenance. The token is Seen. The maintenance wording is Guessed.
2. Call `WSLogOn.Validar` with the token, the user name, and the password. An empty text means the password was accepted. Any other text is a refusal. Seen.
3. Call `WSLogOn.GetRoles` with the token. A login with one role answers `{"OK": [{"Identificador": "<role id>"}]}`, and `Error`, `multifactor`, and `Ruta` are absent. Seen with one role. A login with several roles is Read. The client asks the operator to name one with `role_id` and does not guess.
4. Call `WSLogOn.ValidarRol` with the token, the role id, and `evaluarMultifactor` set to false. A plain sign-in answers `OK` true, `OKCuenta` true, and a `RutaHome`. Seen.
5. Read the `RutaHome` page. It lists the guardian and the children. The client refuses a `RutaHome` that points off the portal. Seen.

### What a refusal looks like

The client names a refusal by the words in it. The order of the checks matters, because a portal fault can mention a user name.

| Text the portal sends | The client says | Pauses logins | Label |
| --- | --- | --- | --- |
| `La sesión ha caducado` for a stale token | `token_invalid`, then one more try with a new token | No | Seen |
| `Usuario o código de acceso incorrecto` | `invalid_credentials` | Yes | Seen with a user name that does not exist |
| Words such as `referencia a objeto` or `excepción` | `portal_fault` | No | Guessed |
| Any other refusal text | `refused_login` | Yes | Not applicable |

The wrong-password text was recorded with a user name that does not exist. Nobody sent a wrong password for a real user, because that can lock the account. An unknown text counts as a refusal and pauses logins, which is the safe way to be wrong. A refusal that mentions a token is taken for the stale token, and the retry sends the password once more only after the portal has said that the token was the problem.

### What blocks a sign-in until a person acts

| Sign | The client says | Label |
| --- | --- | --- |
| `GetRoles` has `multifactor` | `mfa_required` | Read |
| `ValidarRol` carries `CambiarPws` | `action_required_in_portal` for a password change | Read |
| `ValidarRol` carries `TxtLegales` | `action_required_in_portal` for legal terms | Read |
| `ValidarRol` has `OKCuenta` set to false | `action_required_in_portal` for an account step | Read |
| `ValidarRol` carries `MatOnline` | `action_required_in_portal` for online enrollment | Read |
| `ValidarRol` carries `muetraOpClassroom` | `action_required_in_portal` for a classroom option | Read |

The portal spells that last field `muetraOpClassroom`, and the client matches it as the portal does. These screens ask a person to read or choose something, so a script that clicked through them would answer for the guardian. The client stops, pauses logins, and says which screen to open in a browser.

The multifactor flow has its own calls in the portal's scripts, and the client does not use them. The portal also offers a Google and a Microsoft sign-in, which were turned off where the earlier client ran, and it showed no captcha there. All of this is Read.

## Session state

The portal keeps state for each session on its server.

| State | Set by | Label |
| --- | --- | --- |
| The folder that the message list shows | `CarpetaSeleccionada` | Seen |
| The message that is open | Loading `Comunicado.aspx` | Seen |
| The person whose agenda is open | Loading `PaginaAgenda.aspx` | Seen |
| The active child | A script call this client never makes | Read |

A feed or a call that depends on this state names nothing in the request. The agenda feed carries no person, and the message data call carries no message id. A recipe that does several requests in a row must run without another request in between, so each account has one lock and a recipe holds it from its first request to its last.

A recipe must never ask the gateway that runs it for another turn. The lock cannot be taken twice by the same work, so a second request from inside a turn would wait for itself and say nothing. The gateway raises an error at once instead.

### Cookies and lifetime

- `.ASPXAUTH` carries the session. Sent alone it is enough to load the home page. `AC_SessionId` alone is not, the two 14-day cookies alone are not, and an anonymous `LogOnToken` is not. Seen.
- `AC_SessionId`, `datosUsr`, and `.ASPXAUTH` last for the session. `LastIdInstitucion` and `InicioSesion` last 14 days. All are HttpOnly and Secure. Seen.
- The client keeps cookies in memory, clears the jar at the start of every login, and never writes it to disk.
- A second login does not end the first session. This server can log in without signing the family out of their own browser. Seen.
- The portal's pages run an 18-minute idle timer in the browser, with a poll every minute. The timer lives in the page only. Sessions that sent no traffic for 19, 25, 31, and 40 minutes all loaded the home page. The longest idle time a session survives is not measured. Seen.

### How the gateway checks a session

`CheckSession` does not read the server session. It answers from the counter that the caller sends. Counter 1 gives `IsOk` true. Counters 17, 18, and 19 add a `Mensaje` that says 180, 120, or 60 seconds remain. Counter 20 or more gives `IsOk` false. Two live sessions with different histories gave the same answers. Only a dead session gives a different answer, which is the HTTP 401 above. Seen.

So the gateway trusts a session for 10 minutes after its last success. After that it calls `CheckSession` with the counter 1, and a failure means the session is dead. A real call that gets a 401 or a login redirect means the same. The gateway then logs in once more. A login takes about a second and a half, so nothing keeps a session alive in between.

## The home page

The home page lists the guardian and the children twice, and the client joins the two lists on the person id. Seen.

- `ul.lienzo_hijos` has one `li[hijo]` for each child. The `hijo` attribute is the student id. The photo's `key` is the person id. The full name is in a `<p>`.
- `ul.lista_users` has one `li[onclick]` for each person. The click handler reads `HijoClicked(this,'<person id>','True|False')`, and `True` marks the guardian. The first name is in an `<h3>` and the relation to the guardian is in a `<strong>`.
- A child with no entry in the second list takes the first word of the full name. A home page with no child and no guardian entry is `unexpected_reply`.

## The agenda

The agenda has two steps, and the second depends on the first. Seen.

1. Load `PaginaAgenda.aspx?master=3&TipoAgenda=7&GuidObjeto=<person id>` for a child. The guardian's agenda is `master=1&TipoAgenda=6` with the guardian's person id. The page makes the server remember whose agenda is open.
2. Load `ControladorAgenda.ashx?start=<unix seconds>&end=<unix seconds>&_=<milliseconds>`. The answer is a bare JSON array of FullCalendar entries. The last number is the browser's cache buster.

The feed has quirks that the reader hides.

- The portal honors `start` and ignores `end`. A request for one week and a request for four months give the same answer, which is every entry from `start` to the end of the school year. One child's answer is a few hundred kilobytes. The reader keeps the entries that touch the window and drops the rest, and the server keeps each answer for the agenda cache time before it asks again. Seen.
- A few standing entries dated before the school year, such as old holidays, come back for every request. The window filter drops them. Seen.
- Times are the school's wall time, written `YYYY-MM-DDTHH:MM:SSZ`. The `Z` means nothing. The reader drops it and attaches the school's zone. Seen.
- A lesson `id` names a weekly slot and not one lesson. One lesson is the id plus its local date, and the API's entry id has that shape. Seen.
- `className` says what an entry is. `evHorario` is a lesson, `evEntrevista` is an interview, and `evSecundario` is a school event. A school event titled `festivo`, compared without case and accents, is a holiday. Seen.
- A holiday or an all-day event runs from 00:00 to 00:00 or to 23:59. The reader calls any entry with those times an all-day entry. Seen.
- Public holidays and school breaks still list lessons, so a lesson in the feed does not mean the school is open. Seen.
- `seccion` holds the teacher on a lesson. Seen.
- `tareas`, `actividades`, `anotaciones`, `controles`, and `is_sustitucion` are counters on a lesson. They were zero on every lesson in the recording. The portal may write a raised flag as text, as a number, or as a boolean, so the reader counts any value that is not zero, false, or empty as raised, and a number says how many. A value it does not understand counts as one, because a flag the school raised must not vanish. Guessed.

## Messages

### Folders

`GetArbolCarpetasJSON` answers `nodos`, which is text that holds a JSON list. Each node has an `id`, a `text`, and a count in `attributes[0].spanAdicionalTexto`. The folder ids are strings, not numbers. Seen.

The client serves two of the folders, `IdCarpetaRecibidos` for received and `IdCarpetaEnviados` for sent. The tree also lists drafts and personal folders, and the client leaves them out. Selecting the drafts folder with `CarpetaSeleccionada` answers HTTP 500, so a draft cannot be listed with this call. Seen.

`CarpetaSeleccionada` is session state. Reading sent messages and then received messages needs a second call, and the reader selects the folder before every read.

### The list

The list is a jqGrid feed. It sends JSON with the media type `text/html`, so the client does not trust the media type.

```text
GET /ACWeb/paginas/Comunicacion/Comunicados.aspx
    ?jqGridID=ctl00_ContenidoPagina_ctl00_GridComunicados
    &_search=false&nd=<ms>&rows=<n>&page=<p>&sidx=FechaInicio&sord=desc
```

The answer is `{page, total, records, rows: [{id, cell: [...]}]}`, where `total` counts pages and `records` counts rows. Every row has 11 cells, and the feed works right after a folder selection with no earlier page read. Seen.

| Cell | Holds |
| --- | --- |
| 0 | The message id. It must equal the row's `id`. |
| 1 | An image for the read state. The alt text is `Leído` or `No leído`, and the image name has `sobre_abierto` or `sobre_cerrado`. |
| 2 | The institutional flag as text, `true` or `false`. |
| 3 | An info icon that the client ignores. |
| 4 | The sender. |
| 5 | The subject. |
| 6 | The received date as `dd/mm/yyyy`. |
| 7 | The expiry date, or an empty cell. |
| 8 | The anonymous flag as text. |
| 9 | The category, which can be empty. |
| 10 | An attachment icon. Only whether it is empty counts, because it names the first file and nothing else. |

An empty cell holds `&nbsp` with no semicolon, and the client treats it as empty. A row with a different cell count, a cell that is not text, a date that does not parse, or a row id that differs from cell 0 is `portal_changed`. The client reads 50 rows a page, up to 200 pages, and marks the result `truncated` past that. The list shows no message body.

### One message

Opening a message takes two requests. Seen.

1. Load `Comunicado.aspx?GuidComunicadoOrigen=<id>&TipoComunicado=N&AccionComunicado=1&DestsInicialesCom=&TxtDefaultCom=&AccionExtraCom=`. The page is large and the client does not read it. Loading it makes the server remember the message.
2. Call `GetDatosPaginaComunicado` with `{}`.

The data has no message id, because the server remembers which page was opened. A page can show another message than the one asked for if something else moved the session. The reader checks the publication date, the subject, and the sender against the list row, and refuses the page when they differ. Serving it would put one message's words under another message's id.

The portal sends 22 fields. The client reads 12.

| Field | Used for |
| --- | --- |
| `AdjuntosExistentes` | The files, each with `Id`, `Nombre`, and `Tamanio` |
| `Contestable` | Whether the guardian can reply |
| `Asunto_1`, `Mensaje_1` | The subject and the text |
| `Asunto_2`, `Mensaje_2`, `Asunto_3`, `Mensaje_3` | Two more versions of the subject and the text. The client calls them translations. Read |
| `FechaPublicacion`, `HoraPublicacion` | The time of sending, as `YYYY-MM-DD` and `HH:MM` in the school's zone |
| `NombreEmisor` | The sender. A sent message has an empty sender |
| `NombreHijos` | Free text that names the children the message concerns |

The text is HTML as the school typed it in a rich text editor, so none of it is trusted. `portal/body.py` turns it into safe HTML, plain text, and a list of links.

### Files

A file comes from `ControladorRepositorio.ashx?tipo=6&nombre=<file id>&alias=<file name>`. The portal serves it as `application/octet-stream`, so the client finds the media type from the first bytes of the file. Seen.

The portal serves the files of the message that the session has open. The client therefore opens the message again, reads its page again, and finds the file in the list before any bytes move. A file the school took away or replaced is found out at that point.

The client assumes that a failed download comes back as a web page with status 200. It refuses a page, a size that differs from the size the message lists, and anything over the limit. The check costs nothing when the assumption is wrong. Guessed.

## Lists of one child

The absences of a child come from a grid page, and the meetings come from another one. Both work in two steps, in the order the portal's own page makes them.

1. Load the page with the child in the address, which for the absences is `Justificar.aspx?GuidObjeto=<student id>&ObjetoTipo=6&master=3&contexto_pagina=1`. The page makes the server remember which child is open.
2. Load the same address with the grid's own parameters added. They are `jqGridID`, `_search=false`, `nd` with the time in milliseconds, `rows=500`, `page=1`, `sidx`, and `sord`. The request says that it is an `XMLHttpRequest` and takes the page's address as its referer. The answer is JSON that the portal labels as HTML. It holds `page`, `total`, `records`, and `rows`, and each row has an `id` and a list of `cell` values. A cell is a small piece of HTML.

The client sends both requests in one recipe under the account lock, so no other request comes between them. A cell that holds only spaces or `&nbsp` is empty, and the portal leaves out the semicolon. Seen for the meetings page and for the absences page.

### Absences

The page is `/ACWeb/paginas/incidencias/Justificar.aspx`. Its grid is `ctl00_ctl00_ContenidoPagina_ContenidoPagina_CmptIncidencias_gridJustificar`, and it sorts by `Fecha`, newest first. Seen.

The page lists the days from the first day of the current month to today, and it leaves the box "Pendientes de justificar" unticked. An empty list therefore says only that nothing is recorded in that window. The API repeats this limit in the description of the route. Seen.

Each row has 14 cells. The recording had no rows, so the cell formats come from the page's script and not from a real list. Read.

| Cell | Holds | Field of the API |
| --- | --- | --- |
| 0 | The id, which has to equal the id of the row | `id` |
| 1 | An image that marks an incident that cannot be justified | `justifiable`, false when the image is there |
| 2 | The date as `dd/mm/yyyy` | `occurred_on` |
| 3 | A value | Not read |
| 4 | The month | Not read |
| 5 | The hour | `hour` |
| 6 | The student | Not read |
| 7 | The area | `area` |
| 8 | The teacher | `teacher` |
| 9 | The incident, such as a missed day or a late arrival | `incident` |
| 10 | A note | `note` |
| 11 | Whether the incident was justified | `justified` |
| 12 | The reason that was given | `justification` |
| 13 | A box that says whether the school accepted the reason | `accepted` |

A flag cell is true when it holds a ticked box, `True`, `Sí`, or `1`. It is false when it holds an unticked box, `False`, `No`, or `0`. Any other text makes the flag unknown, and the API shows it as `null`. Guessed.

A row with another count of cells, a date that the reader cannot read, or a first cell that differs from the id of the row is `portal_changed`.

The page's justify action calls `WSComunicados.RecuperarRutaComunicadoJustificar` and then moves the whole window to a route that belongs to the session. A plain call cannot follow it, so the server reads the list and leaves the justification to the portal. Read.

### Meetings

The page is `/ACWeb/paginas/Grids/Entrevistas.aspx`, and it takes the same address parameters as the absences page. Its grid is `ctl00_ctl00_ContenidoPagina_ContenidoPagina_CmptEntrevistas_gridReuniones1`, and the client asks for it sorted by `Unbound_Mes asc, Fecha`. The reader sorts the rows again by start and id, so the order does not depend on the portal's sort. Seen.

Each row has 12 cells, as a real list showed once. Seen.

| Cell | Holds | Field of the API |
| --- | --- | --- |
| 0 | The id, which has to equal the id of the row | `id` |
| 1 | An icon whose title is the state | `state` and `state_label` |
| 2 | An icon for the people who take part | Not read |
| 3 | The time that remains | Not read |
| 4 | The month | Not read |
| 5 | The date as `dd/mm/yyyy` | `starts_at`, with cell 6 |
| 6 | The start time as `HH:MM` | `starts_at`, with cell 5 |
| 7 | Who asked for the meeting | `requested_by` |
| 8 | The person who is responsible | `staff` |
| 9 | The child and the class | Not read |
| 10 | The notes | `note` |
| 11 | A small file icon | Not read |

The date and the time are clock times at the school. The reader gives them the offset that the school has on that day.

Only the state word `Aceptada` was seen. The reader matches the stems below, which are a guess. A label that has the words of two states reads as the first of them in the order of the table, so a cancelled meeting never reads as one that is still on. A label that matches none of them is `unknown`, and the API passes the portal's own word as `state_label` in every case, so a client can read a word that the table does not know. Guessed.

| State | Stems that the reader matches |
| --- | --- |
| `cancelled` | `cancelad`, `anulad` |
| `declined` | `rechazad`, `denegad` |
| `accepted` | `aceptad`, `confirmad` |
| `done` | `realizad`, `celebrad` |
| `requested` | `solicitad`, `pendiente`, `propuest` |

A meeting that the school holds for a whole group has been seen with the start `00:00` and the clock time in the note. The reader passes both as they are, because the note is free text. Seen.

A row with another count of cells, a first cell that differs from the id of the row, or a date or a start time that the reader cannot read is `portal_changed`.

### Free hours of the staff

Two script calls answer, and the table of calls above lists both. They take the id of a member of the staff, which is the `Valor` of the staff list.

`GetFechasDisponibles` lists the free hours of one month as texts written `year,month,day` with no padding. It lists one text for each free hour, so a day with three free hours appears three times, and the reader keeps each day once. `GetHorasByFecha` lists the free hours of one day as texts written `HH:MM-HH:MM`. Its date has to be ISO text, because the `/Date(ms)/` text that the page's own proxy sends is accepted and finds no hours. A person with nothing free gets `{}` from both calls. Seen.

The reader refuses a text that it cannot read, and an hour that ends when it starts or before, as `portal_changed`. The portal gives plain clock times, and the API adds the offset that the school has on that day.

The portal's page offers the staff list of one child before it asks for hours, and the server does the same. It reads the hours only of an id on the staff list of the same child, and it answers `staff_not_found` without a portal call for any other id. Read.

Which days the portal offers is the school's rule. The simulator offers hours only from tomorrow on, and a real portal can differ. Nobody has watched what a real portal answers for a month that is over or for today.

## The tracking widget and the staff list

`GetWPSeguimiento` answers five HTML fragments. Each holds its count in an `<em>N</em>`. The recording had every counter at zero, so the markup for a count above zero is Read. A fragment with no `<em>` number is `portal_changed`.

`GetEmpleadosByHijo` answers a list of `Valor`, which is the staff id, and `Texto`, which reads `Name (Role)`. The role is the last bracketed part. The portal sometimes lists entries with no valid staff id, and the client skips them. Seen.

## What nobody has seen

- Whether opening a message page marks the message read. The client assumes that it might. The server never calls a read-state method, and an unread message in the portal may turn read when the server reads it. Nobody has run the experiment, because it writes read state on the school's side.
- How long a session survives idle. It is more than 40 minutes.
- Any request from a hosting provider's address. The earlier client ran from a home connection, and a portal may treat other addresses differently.
- A login with several roles, the multifactor step, and each screen in the table above.
- The wording of a maintenance page.
- A counter above zero in the tracking widget and in the agenda.
- A row of the absences grid. The cell formats come from the page's script, and the recording had no rows.
- A meeting in any state but `Aceptada`. The other state words are guesses, and a word that the reader does not know shows as `unknown`.
- What the portal answers for the free hours of a month that is over or of today. The simulator's rule of hours from tomorrow on is its own.
- What the school-year rollover looks like, both in the screens it may add to the login and in the agenda.
- What a real wrong password does to a real account. The design assumes that it can lock it.

## What the portal offers and this project does not call

These calls are not in the allowlist, so the server cannot send them. The notes are for whoever builds the next reader.

- Justifying an absence. The page's justify action moves the whole window to a route that belongs to the session, so a plain call cannot follow it. The page also has a popup that announces an absence, and that is a write. Read.
- Forms and authorizations. The list is the message grid with `autorizaciones=1` on the page. The recording had no forms, so the shape of one is not known.
- Writes. Meeting requests, replies, new messages, and absence announcements all have calls in the portal's scripts. None has run on a real portal. Read.

## When the portal changes

A change in shape shows as `portal_changed` or `unexpected_reply`. Follow these steps.

1. Read the error. The `detail` names the reader and the part, such as `feed row 3: 10 cells instead of 11`. The reply itself never leaves the server, because it holds a family's data.
2. Look at the real page. Sign in with a browser, open the developer tools, switch to the network tab, and repeat what the page does. Save what you need in a file outside the repository. Remove names and ids before you quote anything in an issue.
3. Write a test with a literal expected value for the new shape, and watch it fail.
4. Change the reader and the simulator together. The simulator in `src/alexia_api/sim` repeats each path and shape as literals and imports nothing from `portal`, so a mistake in the reader cannot hide behind the same mistake in the fake.
5. Run `pixi run -e dev check`.
6. Change the label in this file to Seen only when a person watched a real portal do it. A simulator test never earns that label.

## Add a call

1. Add a `WsCall` row to `portal/allowlist.py` with the effect `read`. A row with the effect `write` is refused unless the operator turned writes on.
2. Add the request and reply models to `portal/wire.py`.
3. Write a reader in its own module under `portal/`. It takes the session it is given and returns domain models. A reader never calls the gateway.
4. Add a route and a fault switch to the simulator.
5. Add a row to the tables above, with its label.
