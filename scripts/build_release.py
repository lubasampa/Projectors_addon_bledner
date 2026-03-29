from __future__ import annotations

import argparse
import fnmatch
from pathlib import Path
import tomllib
import zipfile


ROOT_DIR = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT_DIR / "blender_manifest.toml"


def load_manifest() -> tuple[str, str, list[str]]:
    data = tomllib.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    build = data.get("build", {})
    exclude_patterns = list(build.get("paths_exclude_pattern", []))
    return data["id"], data["version"], exclude_patterns


def should_exclude(relative_path: str, is_dir: bool, patterns: list[str]) -> bool:
    path_name = Path(relative_path).name
    candidates = {relative_path, path_name}

    if is_dir:
        candidates.update({f"{relative_path}/", f"{path_name}/"})

    for pattern in patterns:
        normalized_pattern = pattern.rstrip("/")
        if pattern.endswith("/"):
            if relative_path == normalized_pattern or relative_path.startswith(f"{normalized_pattern}/"):
                return True
            if path_name == normalized_pattern:
                return True

        if any(fnmatch.fnmatch(candidate, pattern) for candidate in candidates):
            return True

    return False


def collect_files(patterns: list[str]) -> list[Path]:
    files: list[Path] = []

    for path in ROOT_DIR.rglob("*"):
        relative_path = path.relative_to(ROOT_DIR).as_posix()
        if should_exclude(relative_path, path.is_dir(), patterns):
            continue
        if path.is_file():
            files.append(path)

    return sorted(files)


def build_archive(output_dir: Path) -> Path:
    addon_id, version, exclude_patterns = load_manifest()
    archive_path = output_dir / f"{addon_id}-{version}.zip"
    files_to_package = collect_files(exclude_patterns)

    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in files_to_package:
            archive.write(file_path, arcname=file_path.relative_to(ROOT_DIR).as_posix())

    return archive_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a clean release ZIP for the Blender add-on.")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT_DIR / "builds"),
        help="Directory where the release ZIP will be written.",
    )
    args = parser.parse_args()

    archive_path = build_archive(Path(args.output_dir).resolve())
    print(archive_path)


if __name__ == "__main__":
    main()
