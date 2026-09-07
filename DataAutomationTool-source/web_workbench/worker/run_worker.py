from __future__ import annotations

import multiprocessing
import os

from web_workbench.worker.api import create_server


HOST = "127.0.0.1"
PORT = 18137


def main() -> None:
    multiprocessing.freeze_support()
    secret = os.environ["DATA_AUTOMATION_SESSION_SECRET"]
    server = create_server(HOST, PORT, session_secret=secret)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
