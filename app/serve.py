"""Dev-server entry point: `python -m app.serve`.

Binds 127.0.0.1 on $PORT (default 8420, same as `make run`), so tooling
that assigns a port via the environment can run alongside a manually
started instance on the default port.
"""

import uvicorn

from .config import settings

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
