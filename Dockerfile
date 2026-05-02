FROM python:3.11-slim

# install node for the codex / claude CLIs
RUN apt-get update && apt-get install -y curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# install agent CLIs
# @anthropic-ai/claude-code — the Claude Code CLI harness
# @openai/codex — the OpenAI Codex CLI
RUN npm install -g @anthropic-ai/claude-code @openai/codex

WORKDIR /app
COPY pyproject.toml ./
COPY kollab/ ./kollab/
RUN pip install --no-cache-dir -e .

EXPOSE 8765

# mount ~/.claude and ~/.codex from the host so auth passes through:
#   docker run -v ~/.claude:/root/.claude -v ~/.codex:/root/.codex -v ~/.kollab:/root/.kollab kollab
VOLUME ["/root/.kollab"]

CMD ["kollab"]
