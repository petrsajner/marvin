"""Keep desktop launchers connected to their own installation's data."""
from pathlib import Path


def belongs_to_installation(payload: dict, root: Path, version: str | None = None) -> bool:
    data_root = payload.get("data_root")
    if not isinstance(data_root, str) or not data_root:
        return False
    return (payload.get("mode") == "workspace"
            and (version is None or payload.get("version") == version)
            and Path(data_root).resolve() == root.resolve())
