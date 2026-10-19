# Use it as a git submodule

Your own project can hold this server as a git submodule. Your repository then records the exact version of the server that it uses, and you move to a newer one when you choose. This page shows how to add the server, run it from your project, keep your settings and keys out of the submodule, and update it.

The examples put the submodule in `vendor/alexia-familia-api`. Any folder works if you change the path in each command.

## Add it

```bash
git submodule add -b main https://github.com/GlitchInstitute/alexia-familia-api.git vendor/alexia-familia-api
git commit -m "Add alexia-familia-api"
```

The commit holds two things. The file `.gitmodules` names the address and the branch, and the folder `vendor/alexia-familia-api` records one commit of the server. Your repository holds none of the server's files.

This starts at the newest commit of `main`. To start at a release instead, check out its tag in the folder and commit the folder again. A release is a tag that reads `v` and a version, such as `v1.2.3`.

```bash
git -C vendor/alexia-familia-api checkout TAG
git add vendor/alexia-familia-api
git commit -m "Pin alexia-familia-api to TAG"
```

## Clone a project that has it

A plain `git clone` leaves the folder empty. Ask for the submodule when you clone, or fetch it afterwards.

```bash
git clone --recurse-submodules https://example.test/you/your-project.git
```

In a clone that exists already, run this instead.

```bash
git submodule update --init
```

The CI of your project needs the same step. In GitHub Actions, set `submodules: true` on the `actions/checkout` step.

## Run it from your project

The server needs only pixi. Run it through the manifest of the submodule, from the folder of your own project.

```bash
pixi run --manifest-path vendor/alexia-familia-api/pixi.toml alexia-api serve
```

The first run installs the environment into `vendor/alexia-familia-api/.pixi`. The submodule ignores that folder, so `git status` in your project stays clean.

A command written this way runs in the folder where you type it. The server reads `alexia-api.toml` from there and keeps its `state` folder there, so neither lands inside the submodule. [Configuration](configuration.md#find-the-file) explains how the server finds its settings.

The other guides write `alexia-api doctor`, `alexia-api keys create phone`, and so on. In your project, put `pixi run --manifest-path vendor/alexia-familia-api/pixi.toml` in front of each one.

Do not use the short tasks of the submodule, such as `serve` and `doctor`, from your project. A task runs in the folder of the submodule, where it finds none of your settings. If you want a task anyway, set `ALEXIA_API_CONFIG` to an absolute path first.

## Keep your files out of the submodule

The submodule is a clone of a public repository. A file written into it could end up in a commit that you did not mean to make, so your settings and keys stay in your project.

- Run every command from the folder of your project, as shown above.
- Add three paths to the `.gitignore` of your project, because the `.gitignore` of the server covers only its own folder. The settings file names your school's address, the `state` folder holds the hashes of your keys, and `.env` holds your portal login when you use Compose.

  ```text
  /alexia-api.toml
  /state/
  /.env
  ```

- Keep the portal login out of every file that you commit. [Configuration](configuration.md#keep-passwords-out-of-the-file) shows how.
- Do not commit inside the submodule unless you mean to send the change to the public repository. Run the [privacy check](../CONTRIBUTING.md#keep-your-familys-names-out) first, with a list of your own names.

Tell your formatters and linters to skip the folder too. Some files in it, such as `docs/openapi.json`, are written by a generator and must stay as it wrote them. A formatter that rewrites them makes the submodule show as modified.

## Run it with Docker Compose

Copy the `alexia-api` service and the `data` volume from `vendor/alexia-familia-api/compose.yaml` into the Compose file of your project. Then change one line.

```yaml
services:
  alexia-api:
    build: ./vendor/alexia-familia-api
```

That line replaces `build: .`, so Compose builds the image from the folder of the submodule. Compose reads the other paths of the service, `./alexia-api.toml` and `.env`, from the folder of your own Compose file, so they point at your project. If your project already has a volume called `data`, give this one another name in both places. [Deployment](deployment.md#docker-compose) explains every line of the service.

## Make a client from the OpenAPI file

The file `vendor/alexia-familia-api/docs/openapi.json` describes every route of the version that you pinned, and a test keeps it equal to what the server serves. A client generator reads it directly, so your client changes only when you update the submodule. This command writes types for TypeScript.

```bash
npx openapi-typescript vendor/alexia-familia-api/docs/openapi.json --output src/alexia-api.d.ts
```

[The API guide](api-guide.md#the-openapi-description) lists the conventions that every route shares.

## Update it

Read the [changelog](../CHANGELOG.md) for the version you move to. Then pick a version yourself, or follow the branch.

To pick a version, fetch and check it out in the folder.

```bash
git -C vendor/alexia-familia-api fetch --tags
git -C vendor/alexia-familia-api checkout TAG
```

To follow the newest commit of the branch that `.gitmodules` names, run this.

```bash
git submodule update --remote vendor/alexia-familia-api
```

Either way, `git status` now shows the folder as modified. Commit it to record the new version.

```bash
git add vendor/alexia-familia-api
git commit -m "Update alexia-familia-api"
```

Anyone who pulls this commit runs `git submodule update --init` to get the same version. To install what the new lock file asks for before you restart the server, run `pixi install --locked --manifest-path vendor/alexia-familia-api/pixi.toml`.
