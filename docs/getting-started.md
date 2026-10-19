# Getting started

This guide takes you from nothing to a server that shows your own children's school data. You need to open a terminal and paste commands. You do not need to write code.

You will do three things. First you try the demo, which needs no account. Then you connect your own portal login. Then you ask for your children.

## What you need

- A computer with macOS, Linux, or Windows 10 or newer.
- The user name and the password that you use for the school's parent portal.
- The address of your school's login page. Open the portal in a browser, sign out, and copy the address from the address bar. It looks like `https://portal.example.test/ACWeb/LogOn.aspx?key=your-school-key`.
- Your school's permission. This tool signs in with your login the way you do in a browser, and it is not an official tool. Check that the school allows automated access, and stop if it asks you to.

## Install pixi

[pixi](https://pixi.sh) installs Python and every package this project needs, so you install nothing else by hand.

On macOS and Linux, paste this into a terminal.

```bash
curl -fsSL https://pixi.sh/install.sh | sh
```

On Windows, paste this into PowerShell.

```powershell
powershell -ExecutionPolicy ByPass -c "irm -useb https://pixi.sh/install.ps1 | iex"
```

Open a new terminal window afterward, and check that it works.

```bash
pixi --version
```

## Get the project

```bash
git clone https://github.com/GlitchInstitute/alexia-familia-api.git
cd alexia-familia-api
```

Without git, open the project's page on GitHub, choose Code and then Download ZIP, unpack the file, and open a terminal in the new folder. Run every command below from the project folder.

## Try the demo

```bash
pixi run demo
```

The first run downloads Python and the packages, which takes a minute. The demo then prints a key and a list of requests that you can copy. Everything it shows is made up, and everything it changes is thrown away when you stop it.

Open `http://127.0.0.1:8000/docs`, press Authorize, and paste the key. Then open `GET /v1/accounts/{account}/children`, press Try it out, type `marta` as the account, and press Execute. The two children in the answer are made up.

The demo also prints an address that a calendar app on the same computer can subscribe to. It shows the lessons of the made-up children next to your own events. Remove that calendar from the app when you stop the demo. The [calendar guide](calendars.md#subscribe) shows how to subscribe.

Press Ctrl+C in the terminal to stop the demo.

## Connect your account

Run these steps from the project folder, in one terminal window.

1. Write the settings file. Replace the address with the one from your school.

   ```bash
   pixi run init --account family --login-url "https://portal.example.test/ACWeb/LogOn.aspx?key=your-school-key"
   ```

   The name after `--account` goes into web addresses, so use lower case letters, digits, and hyphens. One account holds all the children of one login. The command writes `alexia-api.toml`, which holds no password.

2. Put your login in the environment, so that no file holds it. The command above names the two variables `PORTAL_FAMILY_USERNAME` and `PORTAL_FAMILY_PASSWORD`. On Windows, [use the PowerShell form](#windows).

   ```bash
   export PORTAL_FAMILY_USERNAME='your user name'
   export PORTAL_FAMILY_PASSWORD='your password'
   ```

   The single quotes stop the shell from reading a `$` or a `!` in your password. If your password holds a single quote, write it as `'\''` inside the quotes.

3. Make a key for your phone or your program. The key appears once, so copy it.

   ```bash
   pixi run keys create phone
   ```

4. Check the setup. This sends nothing to the school.

   ```bash
   pixi run doctor
   ```

   Each line starts with `ok`, `warn`, `fail`, or `stop`. A line that is not `ok` says what to fix. The [troubleshooting guide](troubleshooting.md) explains each one.

5. Start the server.

   ```bash
   pixi run serve
   ```

   Leave this window open. The server runs until you press Ctrl+C.

A wrong password can lock an account at the school. The server therefore stops trying after the first refused login, and it waits for you. If that happens, [follow these steps](troubleshooting.md#every-request-says-breaker_open).

## Look at your children

Open a second terminal window and ask for the children of your account. Replace `YOUR_KEY` with the key from step 3.

```bash
curl -H "Authorization: Bearer YOUR_KEY" http://127.0.0.1:8000/v1/accounts/family/children
```

The first request makes the server sign in to the portal, so it takes a moment. The answer lists each child with an id and a short name such as `lucia`. Every other address that belongs to a child uses that id or that name. You can also use the `/docs` page, as in the demo.

## Where to go next

| You want to | Read |
| --- | --- |
| Keep the server running all the time | [Deployment](deployment.md) |
| See the school's agenda in your calendar app | [Calendars](calendars.md) |
| Use several children, or the logins of both parents | [Children and accounts](children-and-accounts.md) |
| Write a program or a dashboard | [API guide](api-guide.md) |
| Fix a problem | [Troubleshooting](troubleshooting.md) |

## Windows

The steps above work on Windows with these changes.

- Use PowerShell. Set a variable with `$env:NAME = 'value'`, and use single quotes, because double quotes make PowerShell read a `$`. Write a single quote inside the value twice.

  ```powershell
  $env:PORTAL_FAMILY_USERNAME = 'your user name'
  $env:PORTAL_FAMILY_PASSWORD = 'your password'
  ```

- Set the variables in the same window where you run `pixi run serve`. A variable that you set in one window does not exist in another.
- Type `curl.exe` and not `curl`. In Windows PowerShell, `curl` is another name for `Invoke-WebRequest`, which takes different options.

  ```powershell
  $env:KEY = 'YOUR_KEY'
  curl.exe -H "Authorization: Bearer $env:KEY" http://127.0.0.1:8000/v1/accounts/family/children
  ```

- Windows PowerShell 5 writes UTF-16 when you redirect with `>`, and a program that reads the file as UTF-8 then fails. Use an option that writes the file itself, such as `pixi run openapi --output openapi.json`.
- Put an address that holds an `&` in quotes, or the shell cuts it at the `&`.
- End a line with a backtick, not a backslash, to continue a command on the next line.
- For Docker, use [Compose](deployment.md#docker-compose). Its file works the same way in PowerShell.
