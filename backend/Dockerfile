FROM python:3.11-slim AS lint

WORKDIR /app

COPY requirements.txt requirements-dev.txt /app/
COPY constraints.txt /app/constraints.txt
RUN pip install --no-cache-dir -r /app/requirements.txt -r /app/requirements-dev.txt -c /app/constraints.txt

COPY . /app
RUN ruff check /app

FROM python:3.11-slim

WORKDIR /app

# DL3008 (pin apt package versions) is waived for this single RUN on purpose.
# These are WeasyPrint/Pango runtime libs and fonts pulled from the Debian
# suite of whatever python:3.11-slim currently points at. Pinning exact
# versions here means the build breaks with "Version ... was not found" the
# moment the base image picks up a Debian point release, which would take the
# backend, all workers and ai-service down on the next rebuild. The suite is
# already effectively pinned by the base image tag, and --no-install-recommends
# plus the apt list cleanup below keep the layer minimal.
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    shared-mime-info \
    fonts-dejavu-core \
    fonts-noto-core \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
COPY constraints.txt /app/constraints.txt
RUN pip install --no-cache-dir -r /app/requirements.txt -c /app/constraints.txt

RUN groupadd --gid 1001 appuser && useradd --uid 1001 --gid appuser --create-home appuser

RUN mkdir -p /home/appuser/generated_storage && chown appuser:appuser /home/appuser/generated_storage

COPY --chown=appuser:appuser . /app

USER appuser

EXPOSE 8000

# DL3025 (JSON notation for CMD) is waived for the HEALTHCHECK only: the
# `|| exit 1` fallback cannot be expressed in exec form, and rewriting the
# probe would change how an unhealthy backend is reported to compose and to
# the deploy health gate. hadolint 2.12.0 (the version pinned by
# hadolint-action v3.1.0) does not flag this; newer hadolint does, so the
# pragma is here to keep the step green across an action bump.
# hadolint ignore=DL3025
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/system-status', timeout=2)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
