"""Collect path-free facts from the sole production SQLite binding."""

from __future__ import annotations

from hashlib import sha256
from importlib import import_module
from importlib.metadata import version as distribution_version
from pathlib import Path
import platform
import sys
import sysconfig
from types import ModuleType

from djsupport.operational_store.qualification import RuntimeFacts


class RuntimeProbeError(RuntimeError):
    """The selected binding could not produce trustworthy public facts."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"sqlite_runtime_probe_failed:{reason_code}")


def probe_apsw_runtime() -> RuntimeFacts:
    """Interrogate the APSW runtime that would open the Operational Store."""
    try:
        binding = import_module("apsw")
    except ImportError:
        raise RuntimeProbeError("binding_unavailable") from None
    try:
        extension_path = _binding_extension_path(binding)
        compile_options = tuple(
            sorted(str(item) for item in binding.compile_options)
        )
        os_name, os_version, os_product_type = (
            _operating_system_identity()
        )
        return RuntimeFacts(
            binding_distribution="apsw",
            binding_distribution_version=distribution_version("apsw"),
            binding_wrapper_version=str(binding.apsw_version()),
            binding_extension_sha256=_file_sha256(extension_path),
            sqlite_version=str(binding.sqlite_lib_version()),
            sqlite_version_number=int(binding.SQLITE_VERSION_NUMBER),
            sqlite_source_id=str(binding.sqlite3_sourceid()),
            sqlite_compile_options_sha256=_compile_options_sha256(
                compile_options,
            ),
            using_amalgamation=binding.using_amalgamation is True,
            python_implementation=_python_implementation(),
            python_version=(
                f"{sys.version_info.major}."
                f"{sys.version_info.minor}."
                f"{sys.version_info.micro}"
            ),
            python_abi=_python_abi(),
            python_gil_mode=_python_gil_mode(),
            os_name=os_name,
            os_version=os_version,
            os_kernel_release=platform.release(),
            os_product_type=os_product_type,
            architecture=platform.machine(),
        )
    except RuntimeProbeError:
        raise
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        raise RuntimeProbeError("runtime_facts_unavailable") from None


def _binding_extension_path(binding: ModuleType) -> Path:
    value = getattr(binding, "__file__", None)
    if not isinstance(value, str) or not value:
        raise RuntimeProbeError("binding_extension_unavailable")
    return Path(value)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compile_options_sha256(options: tuple[str, ...]) -> str:
    digest = sha256()
    for option in options:
        digest.update(option.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _python_implementation() -> str:
    if sys.implementation.name == "cpython":
        return "CPython"
    return sys.implementation.name


def _python_abi() -> str:
    """Return a stable ABI identity without accepting an unknown value."""
    soabi = sysconfig.get_config_var("SOABI")
    if isinstance(soabi, str) and soabi:
        return soabi
    if (
        sys.implementation.name == "cpython"
        and platform.system() == "Windows"
    ):
        platform_tag = sysconfig.get_platform().replace("-", "_")
        if platform_tag:
            return (
                f"cp{sys.version_info.major}{sys.version_info.minor}-"
                f"{platform_tag}"
            )
    raise RuntimeProbeError("python_abi_unavailable")


def _python_gil_mode() -> str:
    is_enabled = getattr(sys, "_is_gil_enabled", None)
    if callable(is_enabled) and not is_enabled():
        return "free-threaded"
    return "gil"


def _operating_system_identity() -> tuple[str, str, str]:
    name = platform.system()
    if name == "Darwin":
        return (
            "macOS",
            _required_platform_value(platform.mac_ver()[0]),
            "not_applicable",
        )
    if name == "Linux":
        release = platform.freedesktop_os_release()
        distribution = _required_platform_value(release.get("ID"))
        version = _required_platform_value(release.get("VERSION_ID"))
        if distribution == "ubuntu":
            return "Ubuntu", version, "not_applicable"
        return distribution, version, "not_applicable"
    if name == "Windows":
        _release, version, _service_pack, _type = platform.win32_ver()
        return (
            "Windows",
            _required_platform_value(version),
            _windows_product_type(),
        )
    raise RuntimeProbeError("platform_identity_unavailable")


def _required_platform_value(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeProbeError("platform_identity_unavailable")
    return value


def _windows_product_type() -> str:
    product_type = getattr(sys.getwindowsversion(), "product_type", None)
    try:
        return {
            1: "workstation",
            2: "domain_controller",
            3: "server",
        }[product_type]
    except KeyError:
        raise RuntimeProbeError("platform_identity_unavailable") from None
