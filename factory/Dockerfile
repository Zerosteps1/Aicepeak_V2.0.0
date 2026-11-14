# Build from trusted base only. Runtime resolves this image to its sha256 ID.
# No provider credentials or host home directories enter the image.
FROM node:26.13.0-bookworm-slim@sha256:add5c17c14752c54d2f3d519ec46a3815684d41c33f198bcb09fb998f7dcbf68

RUN apt-get update \
    && apt-get install --yes --no-install-recommends python3 git ca-certificates ripgrep \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/factory-clients
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --include=optional --no-audit --no-fund \
    && PATH="/opt/factory-clients/node_modules/.bin:$PATH" \
    && test "$(codex --version)" = "codex-cli $(node -p "require('./package.json').dependencies['@openai/codex']")" \
    && test "$(claude --version)" = "$(node -p "require('./package.json').dependencies['@anthropic-ai/claude-code']") (Claude Code)" \
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
