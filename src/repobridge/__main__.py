"""
`python -m repobridge` -- start the server on the host and port the platform assigns.

**Why this exists.** The README's local instruction is `uvicorn repobridge.main:app`, which
defaults to 127.0.0.1:8000. On a platform that is wrong twice: the port is assigned through
the environment and differs every deploy, and binding to loopback means the container
starts, reports healthy, and receives no traffic -- the single most common reason a first
deployment appears to work and does not.

Reading `PORT` is the near-universal convention (Render, Fly, Railway, Cloud Run, Heroku).
`HOST` is less standard, so it defaults to `0.0.0.0` here rather than to the local default:
a process started this way is being started *for* a platform. Anyone wanting loopback can
say so with `REPOBRIDGE_HOST`.

**One worker, deliberately.** The rate limits in `core/limits.py` are per-process, in
memory, so two workers would mean two independent counters and an effective limit of double
what the operator configured. For a demo instance one worker is also plenty. This is stated
here, in the README, and in the startup log, because it is the kind of thing that is only
noticed when the bill arrives.
"""

from __future__ import annotations

import logging

import uvicorn

from repobridge.config import get_bind_address, get_deployment_config

logger = logging.getLogger("repobridge")


def main() -> None:
    host, port = get_bind_address()
    deployment = get_deployment_config()

    # A platform-assigned port with no host override means "listen on every interface".
    # Keeping 127.0.0.1 there would bind to loopback inside the container and drop
    # everything the platform routed to it.
    import os

    if not any(os.getenv(name) for name in get_deployment_config().host_env_vars):
        host = "0.0.0.0"  # noqa: S104 - binding a container to its own interfaces

    logger.info(
        "Starting RepoBridge on %s:%s (mode=%s, one worker: rate limits are per-process)",
        host,
        port,
        deployment.mode,
    )
    uvicorn.run("repobridge.main:app", host=host, port=port, workers=1, log_level="info")


if __name__ == "__main__":
    main()
