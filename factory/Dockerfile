# Build from trusted base only. Runtime resolves this image to its sha256 ID.
# No provider credentials or host home directories enter the image.
FROM node:22.21.1-bookworm-slim

RUN apt-get update \
    && apt-get install --yes --no-install-recommends python3 git ca-certificates ripgrep \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/factory-clients
COPY client-tools.lock.json ./package-lock.json
RUN node -e 'const fs=require("fs"); const p=JSON.parse(fs.readFileSync("package-lock.json")).packages[""]; fs.writeFileSync("package.json",JSON.stringify(p));' \
    && npm ci --omit=dev --include=optional --no-audit --no-fund \
    && PATH="/opt/factory-clients/node_modules/.bin:$PATH" \
    && test "$(codex --version)" = "codex-cli 0.164.0" \
    && test "$(claude --version)" = "2.1.311 (Claude Code)" \
    && npm cache clean --force

ENV DISABLE_UPDATES=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/factory-clients/node_modules/.bin:$PATH"
USER 1000:1000
WORKDIR /work
CMD ["python3", "--version"]
