# pp-test-s3-sandbox:dev -- draft sandbox image for Spike S3.
#
# Base pinned by tag AND digest (immutable even if the tag is repointed).
FROM debian:bookworm-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251

# Pin the Node.js major line via NodeSource's setup script, then pin the exact
# apt package version so `apt-get install` is reproducible.
ARG NODE_MAJOR=24
ARG NODE_VERSION=24.9.0-1nodesource1

ENV DEBIAN_FRONTEND=noninteractive \
    PATH=/opt/pp/tools:/home/pp/.local/bin:$PATH

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
ARG UV_VERSION=0.9.6
RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | \
        UV_INSTALL_DIR=/usr/local/bin sh

# pytest + PyYAML via uv-managed pip, installed globally (root site-packages) so
# they are available without a project venv. PyYAML backs spikes/s3/install.py's
# allow-list parsing.
RUN uv pip install --system --break-system-packages pytest==8.3.5 pyyaml==6.0.2

# Non-root user `pp`, and the tool-install directory the CLI allow-list
# installer (spikes/s3/install.py) writes into.
RUN useradd --create-home --shell /bin/bash pp \
    && mkdir -p /opt/pp/tools /workspace \
    && chown -R pp:pp /opt/pp /workspace

VOLUME ["/workspace"]
WORKDIR /workspace
USER pp

CMD ["sleep", "infinity"]
