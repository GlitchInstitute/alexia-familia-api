"""The image and the workflows install the same version of pixi."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIXI_IMAGE = re.compile(r"ghcr\.io/prefix-dev/pixi:(\d+\.\d+\.\d+)")
PIXI_ACTION = re.compile(r"pixi-version:\s*v(\d+\.\d+\.\d+)")


def test_one_version_of_pixi_builds_the_image_and_runs_the_workflows() -> None:
    files = [ROOT / "Dockerfile", *sorted((ROOT / ".github" / "workflows").glob("*.yml"))]
    versions: dict[str, set[str]] = {}
    for path in files:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            found = set(PIXI_IMAGE.findall(text)) | set(PIXI_ACTION.findall(text))
            if found:
                versions[path.name] = found

    assert versions, "no file names a pixi version"
    assert len({version for found in versions.values() for version in found}) == 1, versions
