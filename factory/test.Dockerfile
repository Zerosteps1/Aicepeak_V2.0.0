# Trusted test image for the deterministic checks (tools/factory/engine.py test, tools/factory/sandbox-verify.sh).
# Build from the trusted checkout only. Its tag is derived from this file and every file it copies
# (tools/factory/images.py); runtime resolves the tag to its sha256 ID. No credentials and no provider CLIs.

# Node from the same digest-pinned image as the author image (factory/Dockerfile).
FROM node:26.12.0-bookworm-slim@sha256:742a0fe7320e09e0321222b68165e6ac731d30470e7ea7f98f9bfc3a6e1034fe AS node

# .NET 10 SDK on Ubuntu 24.04 (multi-arch: linux/amd64, linux/arm64); satisfies global.json.
FROM mcr.microsoft.com/dotnet/sdk:10.0.404-noble@sha256:fe0fd4e93bd2fbb47c883b7a6369e5c8d3db8bf01cdc5981f6ee35fbdf3ff4fb

RUN apt-get update \
    && apt-get install --yes --no-install-recommends python3 git ca-certificates libatomic1 \
    && rm -rf /var/lib/apt/lists/*

# Transfer node from node image to microsoft dotnet image
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY tools.lock.json install_tools.py /opt/factory-tools/

RUN python3 /opt/factory-tools/install_tools.py --lock /opt/factory-tools/tools.lock.json --destination /usr/local/bin

# The sandbox runs with a read-only root and a tmpfs /tmp: every home and cache lives there.
ENV HOME=/tmp \
    DOTNET_CLI_HOME=/tmp \
    NUGET_PACKAGES=/tmp/nuget/packages \
    npm_config_cache=/tmp/npm-cache \
    npm_config_update_notifier=false \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    DOTNET_GENERATE_ASPNET_CERTIFICATE=false \
    PYTHONDONTWRITEBYTECODE=1

# Self-checks: exact toolchain versions and every tool the checks call.
RUN test "$(dotnet --version)" = "10.0.404" \
    && test "$(node --version)" = "v26.12.0" \
    && npm --version \
    && python3 -c 'import tomllib' \
    && git --version \
    && actionlint -version \
    && gitleaks version \
    && rm -rf /tmp/* /tmp/.[!.]*
USER 1000:1000
WORKDIR /work
CMD ["python3", "--version"]
