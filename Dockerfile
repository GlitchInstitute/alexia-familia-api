# Builds a small image that runs alexia-familia-api as a user without rights.
#
#   docker build -t alexia-familia-api .
#   docker run --rm -p 127.0.0.1:8000:8000 alexia-familia-api alexia-api demo --host 0.0.0.0
#
# The versions of every package come from pixi.lock, so two builds of one commit hold the same
# packages. Both base images are pinned by digest. Dependabot proposes a newer digest of the
# Ubuntu tag, and the pixi version moves by hand, as CONTRIBUTING.md explains.

FROM ghcr.io/prefix-dev/pixi:0.70.2@sha256:c2d3c9b7041293d90039857bb3cff4c0bbe8c78af1d68254b230575154b85f65 AS build

WORKDIR /app
COPY pixi.toml pixi.lock pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pixi install --locked --environment default

# The image puts the environment on PATH and runs nothing from activate.d. That is only right
# while no package ships an activation script, so a package that adds one stops this build
# and the fix is to start from `pixi shell-hook`.
RUN if [ -d .pixi/envs/default/etc/conda/activate.d ]; then \
      echo "A package now ships an activation script. Use pixi shell-hook in this image." >&2; \
      exit 1; \
    fi


FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac AS runtime

LABEL org.opencontainers.image.title="alexia-familia-api" \
      org.opencontainers.image.description="A self-hosted REST API for the Alexia Familia parent portal." \
      org.opencontainers.image.source="https://github.com/GlitchInstitute/alexia-familia-api" \
      org.opencontainers.image.licenses="MIT"

# The environment is found by the path it was built at, so it keeps that path here.
COPY --from=build /app/.pixi/envs/default /app/.pixi/envs/default
COPY --from=build /app/src /app/src

# The server reads alexia-api.toml from /data and keeps its few files in /data/state, so one
# volume holds everything that has to survive a new container.
RUN groupadd --system --gid 10001 alexia \
 && useradd --system --uid 10001 --gid alexia --no-create-home --shell /usr/sbin/nologin alexia \
 && install --directory --owner=alexia --group=alexia --mode=0700 /data

ENV PATH="/app/.pixi/envs/default/bin:${PATH}" \
    CONDA_PREFIX="/app/.pixi/envs/default" \
    PYTHONUNBUFFERED=1

USER alexia
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8000

# Only the process is checked, so a portal that is down does not make the container unhealthy.
# Change the port here as well when you change it in the command.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]

CMD ["alexia-api", "serve", "--host", "0.0.0.0", "--port", "8000"]
