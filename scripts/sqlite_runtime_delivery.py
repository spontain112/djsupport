#!/usr/bin/env python3
"""Build and qualify DJ Support with one reviewed binary APSW wheel."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
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


APSW_REQUIREMENT = "apsw==3.53.4.0"
APSW_REPOSITORY = "https://github.com/rogerbinns/apsw"
NATIVE_SUFFIXES = (".dylib", ".dll", ".pyd", ".so")
PRIVATE_SUFFIXES = (
    ".sqlite3",
    ".sqlite3-journal",
    ".sqlite3-shm",
    ".sqlite3-wal",
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
        apsw_wheel = _download_binary_wheel(workspace / "apsw")
        catalog = load_artifact_catalog()
        artifact = artifact_for_cell(
            catalog,
            runner_label=runner_label,
            python_version=_python_version(),
            architecture=_architecture(),
        )
        verify_downloaded_wheel(apsw_wheel, artifact)
        _verify_provenance(str(artifact["download_url"]))
        djsupport_wheel = _build_and_inspect(workspace / "dist")
        clean_python = _create_clean_install(
            workspace / "clean",
            apsw_wheel,
            djsupport_wheel,
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


def _download_binary_wheel(destination: Path) -> Path:
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
            APSW_REQUIREMENT,
        ],
        check=True,
    )
    wheels = list(destination.glob("apsw-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("sqlite_runtime_delivery_failed:wheel_resolution")
    return wheels[0]


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


def _build_and_inspect(destination: Path) -> Path:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--outdir",
            str(destination),
            str(REPOSITORY_ROOT),
        ],
        check=True,
    )
    wheels = list(destination.glob("djsupport-*.whl"))
    sources = list(destination.glob("djsupport-*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise SystemExit("sqlite_runtime_delivery_failed:package_build_shape")
    _inspect_wheel(wheels[0])
    _inspect_source(sources[0])
    return wheels[0]


def _inspect_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            _safe_archive_name(name)
            lowered = name.casefold()
            if lowered.endswith(PRIVATE_SUFFIXES):
                raise SystemExit(
                    "sqlite_runtime_delivery_failed:private_package_member"
                )
            if name.startswith("djsupport/") and lowered.endswith(
                NATIVE_SUFFIXES
            ):
                raise SystemExit(
                    "sqlite_runtime_delivery_failed:unexpected_native_member"
                )


def _inspect_source(path: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            _safe_archive_name(member.name)
            if not (member.isfile() or member.isdir()):
                raise SystemExit(
                    "sqlite_runtime_delivery_failed:unsafe_source_member"
                )
            lowered = member.name.casefold()
            if lowered.endswith(PRIVATE_SUFFIXES):
                raise SystemExit(
                    "sqlite_runtime_delivery_failed:private_package_member"
                )
            parts = PurePosixPath(member.name).parts
            relative = "/".join(parts[1:])
            if relative.startswith("djsupport/") and lowered.endswith(
                NATIVE_SUFFIXES
            ):
                raise SystemExit(
                    "sqlite_runtime_delivery_failed:unexpected_native_member"
                )


def _safe_archive_name(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
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


if __name__ == "__main__":
    main()
