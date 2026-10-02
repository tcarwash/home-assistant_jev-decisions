"""Set real publication metadata once a GitHub repository is chosen."""

import argparse
import json
import re
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("repository", help="GitHub owner/repository")
parser.add_argument("--maintainer", required=True, help="GitHub username")
args = parser.parse_args()
if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
    parser.error("Expected owner/repository")
if not re.fullmatch(r"[A-Za-z0-9-]+", args.maintainer):
    parser.error("Invalid GitHub username")
path = Path(__file__).resolve().parents[1] / "custom_components/ha_decisions/manifest.json"
manifest = json.loads(path.read_text())
base = f"https://github.com/{args.repository}"
manifest.update(
    documentation=f"{base}#readme",
    issue_tracker=f"{base}/issues",
    codeowners=[f"@{args.maintainer}"],
)
path.write_text(json.dumps(dict(sorted(manifest.items())), indent=2) + "\n")
print(f"Publication metadata set for {args.repository}")
