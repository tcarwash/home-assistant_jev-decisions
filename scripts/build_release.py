"""Build a manual-install ZIP from an explicit allowlist, excluding local data."""

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
component = ROOT / "custom_components" / "ha_decisions"
version = json.loads((component / "manifest.json").read_text())["version"]
destination = ROOT / "dist" / f"ha_decisions-{version}.zip"
destination.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
    for source in sorted(component.rglob("*")):
        if (
            source.is_file()
            and source.suffix in (".py", ".json", ".yaml")
            and "__pycache__" not in source.parts
        ):
            archive.write(source, source.relative_to(ROOT))
    for source in sorted((ROOT / "examples").glob("*")):
        if source.is_file() and source.suffix in (".json", ".yaml"):
            archive.write(source, source.relative_to(ROOT))
    for name in ("LICENSE", "README.md", "CHANGELOG.md"):
        archive.write(ROOT / name, name)
print(destination)
