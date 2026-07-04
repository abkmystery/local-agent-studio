from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .config import Settings
from .main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Agent Studio service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7331)
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".local-agent-studio")
    parser.add_argument("--runtime-dir", type=Path, default=None)
    parser.add_argument("--auth-token", default="development-token")
    args = parser.parse_args()

    settings = Settings(
        host=args.host,
        port=args.port,
        data_dir=args.data_dir,
        runtime_dir=args.runtime_dir,
        auth_token=args.auth_token,
    )
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
