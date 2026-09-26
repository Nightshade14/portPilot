# portpilot-sandbox:dev -- per-run sandbox image (Lane S, MVP_PLAN 3.8).
#
# Base pinned by tag AND digest (immutable even if the tag is repointed).
ARG BASE_IMAGE=debian:bookworm-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251

# buildctl: the BuildKit *client* only (no daemon), baked into the image and pinned
# by digest, since shellcheck/buildctl publish no sha256 checksums file for this
# release (see config/cli_allowlist.yaml) and the allow-list installer therefore
# structurally refuses them. Talks to the pp-buildkitd sidecar over TCP.
FROM moby/buildkit:v0.33.0@sha256:6c2fa84a6b61ccd72899dde4239f8d5717f05f9a8ca6f3cad185fb1a95a94de3 AS buildkit_client

FROM ${BASE_IMAGE} AS base

ARG NODE_MAJOR=24
ARG NODE_VERSION=24.9.0-1nodesource1
ARG UV_VERSION=0.9.6

ENV DEBIAN_FRONTEND=noninteractive \
    PATH=/opt/pp/tools:/opt/pp/bin:/home/pp/.local/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
        ca-certificates \
        python3 \
        python3-pip \
        gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
    && apt-get install -y --no-install-recommends "nodejs=${NODE_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

# uv: installed via its official installer into a fixed, non-root-owned path so
# both root (build time) and the pp user (runtime) share one binary.
RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | \
        UV_INSTALL_DIR=/usr/local/bin sh

# pytest + PyYAML via uv-managed pip, installed globally (root site-packages) so
# they are available without a project venv. PyYAML backs the host-side installer's
# allow-list parsing (portpilot.sandbox.installer); pytest runs library-tool tests
# and each run's own test suite inside the container.
RUN uv pip install --system --break-system-packages pytest==8.3.5 pyyaml==6.0.2

COPY --from=buildkit_client /usr/bin/buildctl /usr/local/bin/buildctl

# Non-root user `pp`, the tool-install directory the CLI allow-list installer
# writes into (a separate writable volume at runtime, not this image layer -- see
# docs/spikes/S3_SANDBOX.md Goal 3), and /opt/pp/bin for the frozen runner scripts.
RUN useradd --create-home --shell /bin/bash pp \
    && mkdir -p /opt/pp/tools /opt/pp/bin /workspace \
    && chown -R pp:pp /opt/pp /workspace

COPY --chown=pp:pp src/portpilot/sandbox/runner/pp_tool_run.py /opt/pp/bin/pp_tool_run.py
COPY --chown=pp:pp src/portpilot/sandbox/runner/pp_cli_install.py /opt/pp/bin/pp_cli_install.py
COPY --chown=pp:pp src/portpilot/sandbox/runner/pp_check_env.py /opt/pp/bin/pp_check_env.py
RUN chmod 755 /opt/pp/bin/*.py

VOLUME ["/workspace", "/opt/pp/tools"]
WORKDIR /workspace
USER pp

CMD ["sleep", "infinity"]
