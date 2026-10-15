from __future__ import annotations
import uvicorn
from .config import load_config


def main():
    config = load_config()
    uvicorn.run("backend.app.main:app", host=config["host"], port=int(config["port"]), reload=False)


if __name__ == "__main__":
    main()
