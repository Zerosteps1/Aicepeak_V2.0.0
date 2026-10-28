# Build from trusted base only. Runtime resolves this image to its sha256 ID.
# No provider credentials or host home directories enter the image.
FROM node:22.21.1-bookworm-slim@sha256:25b3eb23a00590b7499f2a2ce939322727fcce1b15fdd69754fcd09536a3ae2c

RUN apt-get update \
    && apt-get install --yes --no-install-recommends python3 git ca-certificates ripgrep \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/factory-clients
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --include=optional --no-audit --no-fund \
    && PATH="/opt/factory-clients/node_modules/.bin:$PATH" \
    && test "$(codex --version)" = "codex-cli 0.164.0" \
    && test "$(claude --version)" = "2.1.311 (Claude Code)" \
    && npm cache clean --force

ENV DISABLE_UPDATES=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/factory-clients/node_modules/.bin:$PATH"
COPY tools.lock.json install_tools.py /opt/factory-tools/
RUN python3 /opt/factory-tools/install_tools.py --lock /opt/factory-tools/tools.lock.json --destination /usr/local/bin
USER 1000:1000
WORKDIR /work
CMD ["python3", "--version"]
