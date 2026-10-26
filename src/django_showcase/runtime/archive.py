from __future__ import annotations

import zipfile
from pathlib import Path


def build_showcase_zip(output_dir: Path, filename: str = "showcase.zip") -> Path:
    archive_path = output_dir / filename
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as zip_file:
        for path in sorted(output_dir.rglob("*")):
            if path == archive_path or path.is_dir():
                continue
            zip_file.write(path, arcname=str(path.relative_to(output_dir)))
    return archive_path
