# RepoBridge -- shared demo instance.
#
# A fallback for platforms that cannot auto-detect a Python app, and a way to pin exactly
# what runs. Deliberately plain: one stage, no wheel-building tricks, nothing that has to
# be understood before it can be trusted.
#
#   docker build -t repobridge .
#   docker run -p 8000:8000 \
#     -e REPOBRIDGE_DEPLOYMENT=shared \
#     -e REPOBRIDGE_GITHUB_TOKEN=... \
#     -e REPOBRIDGE_GEMINI_API_KEY=... \
#     -e REPOBRIDGE_STORAGE=ephemeral \
#     repobridge
#
# Keys are passed as environment variables and never baked into the image. An image with a
# key in a layer is a key you cannot revoke by deleting the container.

FROM python:3.12-slim

# Fail fast and log immediately: buffered stdout in a container means the startup line
# that reports the configuration arrives after the first request, or not at all.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a source change does not reinstall the world.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

# The database lives here rather than in the working directory. On a platform with a
# mounted volume this is the mount point; without one it is ephemeral, which is why
# REPOBRIDGE_STORAGE exists and why the UI stops promising that runs can be returned to.
RUN mkdir -p /data && chown -R nobody:nogroup /data /app
ENV REPOBRIDGE_DATABASE_URL=sqlite+aiosqlite:////data/repobridge.db

# Nothing here needs root, and a demo instance accepting URLs from strangers is exactly
# the place not to run as it.
USER nobody

# Overridden by the platform's assigned PORT; present so `docker run -p 8000:8000` works
# with no further arguments.
ENV PORT=8000
EXPOSE 8000

# `python -m repobridge` reads HOST/PORT from the environment and binds 0.0.0.0.
# One worker, deliberately: the rate limits are per-process. See core/limits.py.
CMD ["python", "-m", "repobridge"]
