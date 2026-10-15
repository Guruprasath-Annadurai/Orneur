FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY orca/ ./orca/

RUN uv pip install --system -e ".[postgres]"

# Run as an unprivileged user (UID/GID 10001), not root. The data directory is owned by that user and
# 0700: orca.config._mkdir_owner_only() refuses a state directory it does not own, so an existing
# volume that was written by an older root-running image must be re-owned once -- see
# docs/orneur/status/CONTAINER_NON_ROOT_MIGRATION.md.
RUN groupadd --gid 10001 orneur \
    && useradd --uid 10001 --gid orneur --create-home --home-dir /home/orneur --shell /usr/sbin/nologin orneur \
    && install -d -o orneur -g orneur -m 0700 /home/orneur/.orca

EXPOSE 7337

ENV ORNEUR_HOME=/home/orneur/.orca \
    ORNEUR_OLLAMA_HOST=http://ollama:11434

USER 10001:10001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -f http://localhost:7337/livez || exit 1

CMD ["orca", "serve", "--host", "0.0.0.0", "--port", "7337", "--no-open"]
