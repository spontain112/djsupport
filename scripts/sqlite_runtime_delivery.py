#!/usr/bin/env python3
"""Build and qualify DJ Support with one reviewed binary APSW wheel."""

from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import quote
import venv
import zipfile

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if "__inner__" not in sys.argv:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from djsupport.operational_store.delivery import (
    artifact_for_cell,
    collect_candidate_entry,
    load_artifact_catalog,
    verify_downloaded_wheel,
    verify_installed_delivery,
)


APSW_REPOSITORY = "https://github.com/rogerbinns/apsw"
NATIVE_SUFFIXES = (".dylib", ".dll", ".pyd", ".so")
PRIVATE_SUFFIXES = (
    ".db",
    ".sqlite",
    ".sqlite3",
    ".sqlite3-journal",
    ".sqlite3-shm",
    ".sqlite3-wal",
)
PRIVATE_MEMBER_NAMES = frozenset(
    {
        "backup-manifest.json",
        "config.json",
        "foundation-migration.json",
        "legacy-migration.json",
        "matching-knowledge.json",
        "publication-manifests.json",
        "publication-manifests.transfers.json",
        "transfers.json",
    }
)
PRIVATE_COMPONENT_PREFIXES = (
    ".djsupport_",
    "djsupport-analytics",
    "djsupport-backup-",
    "djsupport-diagnostics",
    "djsupport-migration-",
    "djsupport-operational-events",
    "djsupport-query-export",
    "djsupport-restore-",
    "djsupport-rollback-",
    "djsupport-snapshot-",
    "local-regression",
    "matching-regression",
    "playlist-state",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("collect", "verify", "__inner__"))
    parser.add_argument("--inner-mode", choices=("collect", "verify"))
    parser.add_argument("--wheel")
    parser.add_argument("--runner-label")
    parser.add_argument("--runner-version")
    parser.add_argument("--runner-manifest-url")
    args = parser.parse_args()
    if args.mode == "__inner__":
        _inner(args)
        return
    _outer(args.mode)


def _outer(mode: str) -> None:
    runner_label = _required_public_env("DJ_SUPPORT_RUNNER_LABEL")
    image_version = _required_public_env("ImageVersion")
    image_os = _required_public_env("ImageOS")
    manifest_url = (
        "https://github.com/actions/runner-images/releases/tag/"
        + quote(f"{image_os}/{image_version}", safe="")
    )
    with tempfile.TemporaryDirectory(prefix="djsupport-runtime-delivery-") as raw:
        workspace = Path(raw)
        catalog = load_artifact_catalog()
        apsw_wheel = _download_binary_wheel(
            workspace / "apsw",
            _selected_binding_requirement(catalog),
        )
        artifact = artifact_for_cell(
            catalog,
            runner_label=runner_label,
            python_version=_python_version(),
            architecture=_architecture(),
        )
        verify_downloaded_wheel(apsw_wheel, artifact)
        _verify_provenance(str(artifact["download_url"]))
        djsupport_wheel = _build_and_inspect(workspace / "dist")
        expected_djsupport_wheel = os.environ.get(
            "DJ_SUPPORT_EXPECTED_WHEEL_SHA256"
        )
        if expected_djsupport_wheel is not None:
            _verify_expected_djsupport_wheel(
                djsupport_wheel,
                expected_djsupport_wheel,
            )
        clean_python = _create_clean_install(
            workspace / "clean",
            apsw_wheel,
            djsupport_wheel,
        )
        if expected_djsupport_wheel is not None:
            _verify_installed_candidate_smoke(
                clean_python,
                _candidate_version_from_wheel(djsupport_wheel),
            )
        subprocess.run(
            [
                str(clean_python),
                str(Path(__file__).resolve()),
                "__inner__",
                "--inner-mode",
                mode,
                "--wheel",
                str(apsw_wheel),
                "--runner-label",
                runner_label,
                "--runner-version",
                image_version,
                "--runner-manifest-url",
                manifest_url,
            ],
            cwd=workspace,
            check=True,
        )


def _inner(args: argparse.Namespace) -> None:
    required = (
        args.inner_mode,
        args.wheel,
        args.runner_label,
        args.runner_version,
        args.runner_manifest_url,
    )
    if any(value is None for value in required):
        raise SystemExit("sqlite_runtime_delivery_failed:inner_arguments")
    catalog = load_artifact_catalog()
    artifact = artifact_for_cell(
        catalog,
        runner_label=args.runner_label,
        python_version=_python_version(),
        architecture=_architecture(),
    )
    verify_downloaded_wheel(Path(args.wheel), artifact)
    if args.inner_mode == "collect":
        payload = collect_candidate_entry(
            artifact=artifact,
            catalog=catalog,
            runner_label=args.runner_label,
            runner_version=args.runner_version,
            runner_manifest_url=args.runner_manifest_url,
        )
        marker = "DJ_SUPPORT_SQLITE_RUNTIME_CANDIDATE"
    else:
        payload = verify_installed_delivery(
            artifact=artifact,
            catalog=catalog,
            runner_label=args.runner_label,
            runner_version=args.runner_version,
            runner_manifest_url=args.runner_manifest_url,
        )
        marker = "DJ_SUPPORT_SQLITE_RUNTIME_EVIDENCE"
    print(f"{marker}={json.dumps(payload, sort_keys=True, separators=(',', ':'))}")


def _download_binary_wheel(destination: Path, requirement: str) -> Path:
    destination.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--no-deps",
            "--dest",
            str(destination),
            requirement,
        ],
        check=True,
    )
    wheels = list(destination.glob("apsw-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("sqlite_runtime_delivery_failed:wheel_resolution")
    return wheels[0]


def _selected_binding_requirement(catalog: dict[str, object]) -> str:
    selected = catalog.get("selected_binding")
    if not isinstance(selected, dict):
        raise SystemExit(
            "sqlite_runtime_delivery_failed:selected_binding_unavailable"
        )
    distribution = selected.get("distribution")
    version = selected.get("version")
    if not isinstance(distribution, str) or not isinstance(version, str):
        raise SystemExit(
            "sqlite_runtime_delivery_failed:selected_binding_unavailable"
        )
    return f"{distribution}=={version}"


def _verify_provenance(download_url: str) -> None:
    import certifi

    environment = dict(os.environ)
    environment["SSL_CERT_FILE"] = certifi.where()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pypi_attestations",
            "verify",
            "pypi",
            "--repository",
            APSW_REPOSITORY,
            download_url,
        ],
        env=environment,
        check=True,
    )


def _build_and_inspect(destination: Path, *, quiet: bool = False) -> Path:
    environment = dict(os.environ)
    environment["SOURCE_DATE_EPOCH"] = _source_date_epoch()
    environment["PYTHONHASHSEED"] = "0"
    environment["TZ"] = "UTC"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--outdir",
            str(destination),
            str(REPOSITORY_ROOT),
        ],
        env=environment,
        check=True,
        capture_output=quiet,
        text=quiet,
    )
    wheels = list(destination.glob("djsupport-*.whl"))
    sources = list(destination.glob("djsupport-*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise SystemExit("sqlite_runtime_delivery_failed:package_build_shape")
    _inspect_wheel(wheels[0])
    _inspect_source(sources[0])
    return wheels[0]


def _inspect_wheel(path: Path) -> None:
    tracked = _tracked_repository_files()
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            name = member.filename
            _safe_archive_name(name)
            if member.is_dir():
                continue
            relative = PurePosixPath(name).as_posix()
            _inspect_member_name(relative)
            generated = ".dist-info/" in relative
            if relative not in tracked and not generated:
                raise SystemExit(
                    "sqlite_runtime_delivery_failed:unexpected_package_member"
                )
            with archive.open(member) as source:
                _reject_build_root(source.read())


def _verify_expected_djsupport_wheel(path: Path, expected_sha256: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise SystemExit(
            "sqlite_runtime_delivery_failed:djsupport_wheel_digest"
        )
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        raise SystemExit(
            "sqlite_runtime_delivery_failed:djsupport_wheel_digest"
        ) from None
    if digest != expected_sha256:
        raise SystemExit(
            "sqlite_runtime_delivery_failed:djsupport_wheel_digest"
        )


def _candidate_version_from_wheel(path: Path) -> str:
    prefix = "djsupport-"
    suffix = "-py3-none-any.whl"
    if not path.name.startswith(prefix) or not path.name.endswith(suffix):
        raise SystemExit(
            "sqlite_runtime_delivery_failed:djsupport_wheel_identity"
        )
    version = path.name[len(prefix) : -len(suffix)]
    if (
        re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+(?:(?:\.dev|rc)[0-9]+)?",
            version,
        )
        is None
    ):
        raise SystemExit(
            "sqlite_runtime_delivery_failed:djsupport_wheel_identity"
        )
    return version


def _verify_installed_candidate_smoke(python: Path, expected_version: str) -> None:
    environment = dict(os.environ)
    for name in (
        "SPOTIPY_CLIENT_ID",
        "SPOTIPY_CLIENT_SECRET",
        "SPOTIPY_REDIRECT_URI",
        "BEATPORT_ACCESS_TOKEN",
    ):
        environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    code = (
        "from importlib.metadata import version; "
        "import djsupport; "
        "raise SystemExit(0 if version('djsupport') == __import__('sys').argv[1] "
        "else 1)"
    )
    cli = (
        python.parent / "djsupport.exe"
        if os.name == "nt"
        else python.parent / "djsupport"
    )
    try:
        subprocess.run(
            [str(python), "-I", "-c", code, expected_version],
            cwd=python.parent,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [str(cli), "--help"],
            cwd=python.parent,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit(
            "sqlite_runtime_delivery_failed:installed_candidate_smoke"
        ) from None


def _inspect_source(path: Path) -> None:
    tracked = _tracked_repository_files()
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            _safe_archive_name(member.name)
            if not (member.isfile() or member.isdir()):
                raise SystemExit(
                    "sqlite_runtime_delivery_failed:unsafe_source_member"
                )
            parts = PurePosixPath(member.name).parts
            relative = "/".join(parts[1:])
            if member.isdir():
                continue
            _inspect_member_name(relative)
            generated = (
                relative == "PKG-INFO"
                or relative == "setup.cfg"
                or relative.startswith("djsupport.egg-info/")
            )
            if relative not in tracked and not generated:
                raise SystemExit(
                    "sqlite_runtime_delivery_failed:unexpected_package_member"
                )
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit(
                    "sqlite_runtime_delivery_failed:unsafe_source_member"
                )
            _reject_build_root(source.read())


def _inspect_member_name(name: str) -> None:
    lowered = name.casefold()
    parts = PurePosixPath(lowered).parts
    basename = parts[-1] if parts else ""
    private_component = any(
        part == "reports"
        or part.startswith(PRIVATE_COMPONENT_PREFIXES)
        for part in parts
    )
    private_name = (
        basename in PRIVATE_MEMBER_NAMES
        or "credential" in basename
        or basename.startswith(".env")
        or basename.endswith(PRIVATE_SUFFIXES)
        or ".sqlite3-" in basename
        or private_component
    )
    if private_name:
        raise SystemExit(
            "sqlite_runtime_delivery_failed:private_package_member"
        )
    if lowered.endswith(NATIVE_SUFFIXES):
        raise SystemExit(
            "sqlite_runtime_delivery_failed:unexpected_native_member"
        )


def _reject_build_root(payload: bytes) -> None:
    repository_path = str(REPOSITORY_ROOT)
    markers = {
        repository_path.encode("utf-8"),
        repository_path.replace("\\", "/").encode("utf-8"),
        repository_path.replace("/", "\\").encode("utf-8"),
    }
    if any(marker and marker in payload for marker in markers):
        raise SystemExit(
            "sqlite_runtime_delivery_failed:local_path_in_package"
        )


@lru_cache(maxsize=1)
def _tracked_repository_files() -> frozenset[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit(
            "sqlite_runtime_delivery_failed:tracked_source_unavailable"
        ) from None
    return frozenset(result.stdout.splitlines())


def _safe_archive_name(name: str) -> None:
    posix_path = PurePosixPath(name)
    windows_path = PureWindowsPath(name)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or ".." in posix_path.parts
        or ".." in windows_path.parts
    ):
        raise SystemExit("sqlite_runtime_delivery_failed:unsafe_package_path")


def _create_clean_install(
    destination: Path,
    apsw_wheel: Path,
    djsupport_wheel: Path,
) -> Path:
    venv.EnvBuilder(with_pip=True).create(destination)
    python = (
        destination / "Scripts" / "python.exe"
        if os.name == "nt"
        else destination / "bin" / "python"
    )
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--no-deps",
            str(apsw_wheel),
        ],
        check=True,
    )
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--only-binary=apsw",
            str(djsupport_wheel),
        ],
        check=True,
    )
    return python


def _required_public_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit("sqlite_runtime_delivery_failed:runner_evidence_missing")
    return value


def _python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _architecture() -> str:
    import platform

    return platform.machine()


def _source_date_epoch() -> str:
    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%ct", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit(
            "sqlite_runtime_delivery_failed:source_epoch_unavailable"
        ) from None
    value = result.stdout.strip()
    if not value.isdigit() or int(value) < 1:
        raise SystemExit(
            "sqlite_runtime_delivery_failed:source_epoch_unavailable"
        )
    return value


if __name__ == "__main__":
    main()
