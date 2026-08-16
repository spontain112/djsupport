"""Fail-closed qualification at the Operational Store runtime seam."""

import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from djsupport.operational_store import (
    QualificationManifestError,
    QualificationState,
    RuntimeFacts,
    SQLiteRuntimeUnavailable,
    SQLiteRuntimeQualification,
    probe_apsw_runtime,
)
from djsupport.operational_store.apsw import RuntimeProbeError


SQLITE_3534_SOURCE_ID = (
    "2026-07-24 19:02:57 "
    "bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc"
)


def active_upstream_manifest():
    return {
        "schema_version": 1,
        "policy_id": "sqlite-runtime-qualification/test-v1",
        "selected_binding": {
            "distribution": "apsw",
            "version": "3.53.4.0",
        },
        "withdrawn_sqlite_versions": ["3.52.0"],
        "affected_sqlite_ranges": [
            {
                "minimum": "3.7.0",
                "maximum": "3.51.2",
                "exceptions": ["3.44.6", "3.50.7"],
            }
        ],
        "entries": [
            {
                "evidence_id": "apsw/3.53.4.0/test-wheel",
                "classification": "qualified_upstream",
                "status": "active",
                "selectors": {
                    "binding": {
                        "distribution": "apsw",
                        "distribution_version": "3.53.4.0",
                        "wrapper_version": "3.53.4.0",
                        "extension_sha256": "a" * 64,
                    },
                    "sqlite": {
                        "version": "3.53.4",
                        "version_number": 3053004,
                        "source_id": SQLITE_3534_SOURCE_ID,
                        "compile_options_sha256": "b" * 64,
                        "using_amalgamation": True,
                    },
                    "python": {
                        "implementation": "CPython",
                        "version": "3.14.7",
                        "abi": "cpython-314-darwin",
                        "gil_mode": "gil",
                    },
                    "platform": {
                        "os": "macOS",
                        "version": "15.6.1",
                        "kernel_release": "24.6.0",
                        "product_type": "not_applicable",
                        "architecture": "arm64",
                    },
                },
                "artifact": {
                    "vendor": "PyPI",
                    "filename": (
                        "apsw-3.53.4.0-cp314-cp314-macosx.whl"
                    ),
                    "download_url": (
                        "https://files.example.test/apsw-test-wheel.whl"
                    ),
                    "size_bytes": 123456,
                    "sha256": "c" * 64,
                    "platform_tag": "cp314-cp314-macosx_15_0_arm64",
                    "publisher": {
                        "identity": "synthetic-publisher",
                        "provenance_url": (
                            "https://pypi.example/attestation/test-wheel"
                        ),
                    },
                    "build": {
                        "source_repository_url": (
                            "https://example.test/apsw/source"
                        ),
                        "source_commit": "e" * 40,
                        "workflow_url": "https://ci.example/run/1",
                        "runner_image": {
                            "label": "macos-15",
                            "version": "20260815.1",
                            "manifest_url": (
                                "https://runner.example/macos-15"
                            ),
                        },
                    },
                },
                "activated_at_utc": "2026-08-16T00:00:00Z",
                "revoked_at_utc": None,
                "supersedes_evidence_id": None,
                "status_evidence_id": None,
            }
        ],
    }


def qualified_runtime_facts():
    return RuntimeFacts(
        binding_distribution="apsw",
        binding_distribution_version="3.53.4.0",
        binding_wrapper_version="3.53.4.0",
        binding_extension_sha256="a" * 64,
        sqlite_version="3.53.4",
        sqlite_version_number=3053004,
        sqlite_source_id=SQLITE_3534_SOURCE_ID,
        sqlite_compile_options_sha256="b" * 64,
        using_amalgamation=True,
        python_implementation="CPython",
        python_version="3.14.7",
        python_abi="cpython-314-darwin",
        python_gil_mode="gil",
        os_name="macOS",
        os_version="15.6.1",
        os_kernel_release="24.6.0",
        os_product_type="not_applicable",
        architecture="arm64",
    )


def configure_synthetic_probe(
    monkeypatch,
    tmp_path,
    *,
    python_version=(3, 10, 11),
    python_abi="cpython-310-darwin",
    gil_enabled=None,
    windows_product_type=None,
):
    extension_path = tmp_path / "apsw.so"
    extension_path.write_bytes(b"synthetic apsw extension\n")
    binding = SimpleNamespace(
        __file__=str(extension_path),
        SQLITE_VERSION_NUMBER=3053004,
        apsw_version=lambda: "3.53.4.0",
        sqlite_lib_version=lambda: "3.53.4",
        sqlite3_sourceid=lambda: SQLITE_3534_SOURCE_ID,
        compile_options=("THREADSAFE=1", "ENABLE_FTS5"),
        using_amalgamation=True,
    )
    monkeypatch.setattr(
        "djsupport.operational_store.apsw.import_module",
        lambda name: binding,
    )
    monkeypatch.setattr(
        "djsupport.operational_store.apsw.distribution_version",
        lambda name: "3.53.4.0",
    )
    runtime = SimpleNamespace(
        implementation=SimpleNamespace(name="cpython"),
        version_info=SimpleNamespace(
            major=python_version[0],
            minor=python_version[1],
            micro=python_version[2],
        ),
    )
    if gil_enabled is not None:
        runtime._is_gil_enabled = lambda: gil_enabled
    if windows_product_type is not None:
        runtime.getwindowsversion = lambda: SimpleNamespace(
            product_type=windows_product_type
        )
    monkeypatch.setattr("djsupport.operational_store.apsw.sys", runtime)
    monkeypatch.setattr(
        "djsupport.operational_store.apsw.sysconfig.get_config_var",
        lambda name: python_abi,
    )
    monkeypatch.setattr(
        "djsupport.operational_store.apsw.platform.system",
        lambda: "Darwin",
    )
    monkeypatch.setattr(
        "djsupport.operational_store.apsw.platform.release",
        lambda: "24.6.0",
    )
    monkeypatch.setattr(
        "djsupport.operational_store.apsw.platform.mac_ver",
        lambda: ("15.6.1", ("", "", ""), ""),
    )
    monkeypatch.setattr(
        "djsupport.operational_store.apsw.platform.machine",
        lambda: "arm64",
    )
    return extension_path


class TestRuntimeClassifier:
    def test_exact_reviewed_upstream_runtime_is_qualified(self):
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())

        result = qualification.classify(qualified_runtime_facts())

        assert result.state is QualificationState.QUALIFIED_UPSTREAM
        assert result.evidence_id == "apsw/3.53.4.0/test-wheel"

    def test_unapproved_native_extension_fails_closed(self):
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())
        facts = replace(
            qualified_runtime_facts(),
            binding_extension_sha256="d" * 64,
        )

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "binding_artifact_unapproved"
        assert result.evidence_id is None

    def test_withdrawn_sqlite_release_is_denied_unconditionally(self):
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())
        facts = replace(qualified_runtime_facts(), sqlite_version="3.52.0")

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_WITHDRAWN
        assert result.reason_code == "sqlite_release_withdrawn"

    def test_environment_and_checkpoint_flags_cannot_override_rejection(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("DJSUPPORT_SQLITE_ALLOW_UNQUALIFIED", "1")
        monkeypatch.setenv("DJSUPPORT_SQLITE_JOURNAL_MODE", "delete")
        monkeypatch.setenv("DJSUPPORT_SQLITE_WAL_AUTOCHECKPOINT", "0")
        monkeypatch.setenv("DJSUPPORT_SQLITE_MAINTENANCE_LEASE", "1")
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())
        facts = replace(qualified_runtime_facts(), sqlite_version="3.52.0")

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_WITHDRAWN
        assert result.reason_code == "sqlite_release_withdrawn"

    def test_known_wal_reset_affected_release_is_denied(self):
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())
        facts = replace(
            qualified_runtime_facts(),
            sqlite_version="3.51.2",
            sqlite_version_number=3051002,
        )

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_AFFECTED
        assert result.reason_code == "sqlite_release_affected"

    def test_active_manifest_entry_cannot_admit_an_affected_release(self):
        manifest = deepcopy(active_upstream_manifest())
        manifest["entries"][0]["selectors"]["sqlite"].update(
            {
                "version": "3.51.2",
                "version_number": 3051002,
                "source_id": "2026-01-01 00:00:00 " + "d" * 64,
            }
        )
        facts = replace(
            qualified_runtime_facts(),
            sqlite_version="3.51.2",
            sqlite_version_number=3051002,
            sqlite_source_id="2026-01-01 00:00:00 " + "d" * 64,
        )

        result = SQLiteRuntimeQualification(manifest).classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_AFFECTED
        assert result.reason_code == "sqlite_release_affected"

    @pytest.mark.parametrize(
        ("version", "version_number"),
        [
            ("3.50.7", 3050007),
            ("3.54.0", 3054000),
        ],
    )
    def test_eligible_or_future_versions_need_exact_evidence(
        self,
        version,
        version_number,
    ):
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())
        facts = replace(
            qualified_runtime_facts(),
            sqlite_version=version,
            sqlite_version_number=version_number,
            sqlite_source_id="2026-08-16 00:00:00 " + "d" * 64,
        )

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "evidence_unlisted"

    def test_revoked_exact_evidence_fails_closed(self):
        manifest = deepcopy(active_upstream_manifest())
        manifest["entries"][0]["status"] = "revoked"
        manifest["entries"][0]["revoked_at_utc"] = "2026-08-17T00:00:00Z"
        manifest["entries"][0]["status_evidence_id"] = (
            "sqlite-policy/2026-08-17/revoked"
        )
        qualification = SQLiteRuntimeQualification(manifest)

        result = qualification.classify(qualified_runtime_facts())

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "evidence_revoked"
        assert result.evidence_id == "apsw/3.53.4.0/test-wheel"

    def test_superseded_exact_evidence_fails_closed(self):
        manifest = deepcopy(active_upstream_manifest())
        manifest["entries"][0]["status"] = "superseded"
        manifest["entries"][0]["status_evidence_id"] = (
            "sqlite-policy/2026-08-17/superseded"
        )
        qualification = SQLiteRuntimeQualification(manifest)

        result = qualification.classify(qualified_runtime_facts())

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "evidence_superseded"
        assert result.evidence_id == "apsw/3.53.4.0/test-wheel"

    def test_loaded_policy_is_immutable_from_caller_mutation(self):
        manifest = active_upstream_manifest()
        qualification = SQLiteRuntimeQualification(manifest)
        manifest["entries"][0]["status"] = "revoked"
        manifest["entries"][0]["revoked_at_utc"] = "2026-08-17T00:00:00Z"

        result = qualification.classify(qualified_runtime_facts())

        assert result.state is QualificationState.QUALIFIED_UPSTREAM

    def test_exact_reviewed_downstream_attestation_is_qualified(self):
        manifest = deepcopy(active_upstream_manifest())
        manifest["entries"][0]["classification"] = (
            "qualified_downstream_attestation"
        )
        manifest["entries"][0]["evidence_id"] = (
            "sqlite-wal-reset/vendor/product/build"
        )
        manifest["entries"][0]["artifact"]["vendor"] = "Synthetic Vendor"
        qualification = SQLiteRuntimeQualification(manifest)

        result = qualification.classify(qualified_runtime_facts())

        assert result.state is (
            QualificationState.QUALIFIED_DOWNSTREAM_ATTESTATION
        )
        assert result.reason_code == "downstream_attestation_exact_match"
        assert result.evidence_id == "sqlite-wal-reset/vendor/product/build"

    def test_malformed_runtime_facts_fail_without_echoing_private_values(self):
        private_value = "/Users/example/private/operational-store.sqlite3"
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())
        facts = replace(
            qualified_runtime_facts(),
            sqlite_source_id=private_value,
        )

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "runtime_facts_malformed"
        assert result.diagnostic == {
            "state": "unqualified_unknown",
            "reason_code": "runtime_facts_malformed",
            "evidence_id": None,
        }
        assert private_value not in repr(result.diagnostic)

    def test_non_string_runtime_selector_fails_closed(self):
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())
        facts = replace(qualified_runtime_facts(), python_abi=None)

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "runtime_facts_malformed"

    def test_a_different_sqlite_binding_is_never_substituted(self):
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())
        facts = replace(
            qualified_runtime_facts(),
            binding_distribution="sqlite3",
        )

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "binding_unapproved"

    def test_unknown_source_id_is_rejected_despite_approved_versions(self):
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())
        facts = replace(
            qualified_runtime_facts(),
            sqlite_source_id="2026-07-24 19:02:57 " + "d" * 64,
        )

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "sqlite_source_unapproved"

    def test_unknown_compile_options_are_rejected(self):
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())
        facts = replace(
            qualified_runtime_facts(),
            sqlite_compile_options_sha256="d" * 64,
        )

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "compile_options_unapproved"

    def test_unapproved_sqlite_build_shape_is_rejected(self):
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())
        facts = replace(
            qualified_runtime_facts(),
            using_amalgamation=False,
        )

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "sqlite_build_unapproved"

    def test_sqlite_text_and_numeric_versions_must_be_internally_consistent(self):
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())
        facts = replace(
            qualified_runtime_facts(),
            sqlite_version_number=3053003,
        )

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "runtime_facts_malformed"

    def test_internally_inconsistent_sqlite_version_identity_is_malformed(self):
        manifest = deepcopy(active_upstream_manifest())
        manifest["entries"][0]["selectors"]["sqlite"][
            "version_number"
        ] = 3053003
        facts = replace(
            qualified_runtime_facts(),
            sqlite_version_number=3053003,
        )

        result = SQLiteRuntimeQualification(manifest).classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "runtime_facts_malformed"

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("python_implementation", "PyPy"),
            ("python_version", "bogus"),
            ("python_abi", "bogus"),
            ("python_gil_mode", "unknown"),
        ],
    )
    def test_malformed_python_runtime_domains_fail_closed(
        self,
        field,
        value,
    ):
        qualification = SQLiteRuntimeQualification(
            active_upstream_manifest()
        )
        facts = replace(qualified_runtime_facts(), **{field: value})

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "runtime_facts_malformed"

    def test_wrapper_and_distribution_version_disagreement_is_rejected(self):
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())
        facts = replace(
            qualified_runtime_facts(),
            binding_wrapper_version="3.53.4.1",
        )

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "wrapper_version_unapproved"

    def test_unapproved_platform_architecture_is_rejected(self):
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())
        facts = replace(qualified_runtime_facts(), architecture="x86_64")

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "platform_unapproved"

    def test_qualification_does_not_transfer_between_python_cells(self):
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())
        facts = replace(
            qualified_runtime_facts(),
            python_version="3.10.11",
            python_abi="cpython-310-darwin",
        )

        result = qualification.classify(facts)

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "python_runtime_unapproved"


class TestQualificationManifest:
    def test_manifest_without_a_versioned_contract_is_rejected(self):
        manifest = deepcopy(active_upstream_manifest())
        del manifest["schema_version"]

        with pytest.raises(
            QualificationManifestError,
            match="sqlite_runtime_manifest_invalid",
        ):
            SQLiteRuntimeQualification(manifest)

    def test_revoked_manifest_entry_requires_revocation_data(self):
        manifest = deepcopy(active_upstream_manifest())
        manifest["entries"][0]["status"] = "revoked"

        with pytest.raises(
            QualificationManifestError,
            match="sqlite_runtime_manifest_invalid",
        ):
            SQLiteRuntimeQualification(manifest)

    def test_manifest_evidence_identities_are_unique(self):
        manifest = deepcopy(active_upstream_manifest())
        second_entry = deepcopy(manifest["entries"][0])
        second_entry["selectors"]["platform"]["architecture"] = "x86_64"
        second_entry["artifact"]["filename"] = "synthetic-second-wheel.whl"
        second_entry["artifact"]["sha256"] = "d" * 64
        manifest["entries"].append(second_entry)

        with pytest.raises(
            QualificationManifestError,
            match="sqlite_runtime_manifest_invalid:unique:evidence_id",
        ):
            SQLiteRuntimeQualification(manifest)

    def test_manifest_selector_tuples_are_unambiguous(self):
        manifest = deepcopy(active_upstream_manifest())
        second_entry = deepcopy(manifest["entries"][0])
        second_entry["evidence_id"] = "apsw/3.53.4.0/second-test-wheel"
        second_entry["artifact"]["filename"] = "synthetic-second-wheel.whl"
        second_entry["artifact"]["sha256"] = "d" * 64
        manifest["entries"].append(second_entry)

        with pytest.raises(
            QualificationManifestError,
            match="sqlite_runtime_manifest_invalid:unique:selectors",
        ):
            SQLiteRuntimeQualification(manifest)

    def test_manifest_rejects_path_shaped_diagnostic_evidence_identity(self):
        manifest = deepcopy(active_upstream_manifest())
        manifest["entries"][0]["evidence_id"] = (
            "/Users/example/private/apsw-wheel"
        )

        with pytest.raises(
            QualificationManifestError,
            match="sqlite_runtime_manifest_invalid",
        ):
            SQLiteRuntimeQualification(manifest)

    def test_manifest_can_record_complete_artifact_and_lifecycle_evidence(self):
        manifest = deepcopy(active_upstream_manifest())
        entry = manifest["entries"][0]
        entry["artifact"] = {
            "vendor": "PyPI",
            "filename": "apsw-3.53.4.0-cp314-cp314-macosx.whl",
            "download_url": "https://files.example.test/apsw-test-wheel.whl",
            "size_bytes": 123456,
            "sha256": "c" * 64,
            "platform_tag": "cp314-cp314-macosx_15_0_arm64",
            "publisher": {
                "identity": "synthetic-publisher",
                "provenance_url": (
                    "https://pypi.example/attestation/test-wheel"
                ),
            },
            "build": {
                "source_repository_url": "https://example.test/apsw/source",
                "source_commit": "e" * 40,
                "workflow_url": "https://ci.example/run/1",
                "runner_image": {
                    "label": "macos-15",
                    "version": "20260815.1",
                    "manifest_url": "https://runner.example/macos-15",
                },
            },
        }
        entry["supersedes_evidence_id"] = None
        entry["status_evidence_id"] = None

        result = SQLiteRuntimeQualification(manifest).classify(
            qualified_runtime_facts()
        )

        assert result.state is QualificationState.QUALIFIED_UPSTREAM

    @pytest.mark.parametrize(
        (
            "os_name",
            "os_version",
            "kernel_release",
            "product_type",
            "architecture",
            "runner_label",
        ),
        [
            (
                "Ubuntu",
                "24.04",
                "6.8.0-40-generic",
                "not_applicable",
                "x86_64",
                "ubuntu-24.04",
            ),
            (
                "macOS",
                "15.6.1",
                "24.6.0",
                "not_applicable",
                "arm64",
                "macos-15",
            ),
            (
                "Windows",
                "10.0.26100",
                "10.0.26100",
                "server",
                "AMD64",
                "windows-2025",
            ),
        ],
    )
    def test_manifest_distinguishes_claimed_native_os_cells(
        self,
        os_name,
        os_version,
        kernel_release,
        product_type,
        architecture,
        runner_label,
    ):
        manifest = deepcopy(active_upstream_manifest())
        entry = manifest["entries"][0]
        entry["selectors"]["platform"] = {
            "os": os_name,
            "version": os_version,
            "kernel_release": kernel_release,
            "product_type": product_type,
            "architecture": architecture,
        }
        entry["artifact"]["filename"] = f"synthetic-{runner_label}.whl"
        entry["artifact"]["platform_tag"] = runner_label
        entry["artifact"]["build"]["runner_image"] = {
            "label": runner_label,
            "version": "20260815.1",
            "manifest_url": f"https://runner.example/{runner_label}",
        }
        facts = replace(
            qualified_runtime_facts(),
            os_name=os_name,
            os_version=os_version,
            os_kernel_release=kernel_release,
            os_product_type=product_type,
            architecture=architecture,
        )

        result = SQLiteRuntimeQualification(manifest).classify(facts)

        assert result.state is QualificationState.QUALIFIED_UPSTREAM

    def test_manifest_rejects_malformed_lifecycle_timestamp(self):
        manifest = deepcopy(active_upstream_manifest())
        manifest["entries"][0]["activated_at_utc"] = "later"

        with pytest.raises(
            QualificationManifestError,
            match="sqlite_runtime_manifest_invalid",
        ):
            SQLiteRuntimeQualification(manifest)

    def test_packaged_policy_qualifies_no_artifact_before_issue_167(self):
        qualification = SQLiteRuntimeQualification.packaged()

        result = qualification.classify(qualified_runtime_facts())

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "evidence_unlisted"


class TestApswRuntimeProbe:
    def test_probe_interrogates_the_selected_binding_without_returning_its_path(
        self,
        monkeypatch,
        tmp_path,
    ):
        extension_path = configure_synthetic_probe(monkeypatch, tmp_path)

        facts = probe_apsw_runtime()

        assert facts == RuntimeFacts(
            binding_distribution="apsw",
            binding_distribution_version="3.53.4.0",
            binding_wrapper_version="3.53.4.0",
            binding_extension_sha256=(
                "dda3dd1718606f115a90df359bd0993d674ef383eb995a52a995dc6f86641c26"
            ),
            sqlite_version="3.53.4",
            sqlite_version_number=3053004,
            sqlite_source_id=SQLITE_3534_SOURCE_ID,
            sqlite_compile_options_sha256=(
                "e6bdc0de01d63b4910162c1847d37db5af394866c14ee461b1ce83920bf4ffd4"
            ),
            using_amalgamation=True,
            python_implementation="CPython",
            python_version="3.10.11",
            python_abi="cpython-310-darwin",
            python_gil_mode="gil",
            os_name="macOS",
            os_version="15.6.1",
            os_kernel_release="24.6.0",
            os_product_type="not_applicable",
            architecture="arm64",
        )
        assert facts.sqlite_version_number == 3053004
        assert str(extension_path) not in repr(facts)

    def test_probe_records_python_314_free_threaded_runtime(
        self,
        monkeypatch,
        tmp_path,
    ):
        configure_synthetic_probe(
            monkeypatch,
            tmp_path,
            python_version=(3, 14, 7),
            python_abi="cpython-314t-darwin",
            gil_enabled=False,
        )

        facts = probe_apsw_runtime()

        assert facts.python_version == "3.14.7"
        assert facts.python_abi == "cpython-314t-darwin"
        assert facts.python_gil_mode == "free-threaded"

    def test_probe_separates_product_os_version_from_kernel_release(
        self,
        monkeypatch,
        tmp_path,
    ):
        configure_synthetic_probe(monkeypatch, tmp_path)

        facts = probe_apsw_runtime()

        assert facts.os_name == "macOS"
        assert facts.os_version == "15.6.1"
        assert facts.os_kernel_release == "24.6.0"
        assert facts.os_product_type == "not_applicable"

    @pytest.mark.parametrize(
        ("python_version", "python_abi", "release_label"),
        [
            ((3, 10, 11), "cp310-win_amd64", "10"),
            ((3, 14, 7), "cp314-win_amd64", "2025Server"),
        ],
    )
    def test_windows_2025_numeric_build_is_exactly_qualified(
        self,
        monkeypatch,
        tmp_path,
        python_version,
        python_abi,
        release_label,
    ):
        configure_synthetic_probe(
            monkeypatch,
            tmp_path,
            python_version=python_version,
            python_abi=python_abi,
            windows_product_type=3,
        )
        monkeypatch.setattr(
            "djsupport.operational_store.apsw.platform.system",
            lambda: "Windows",
        )
        monkeypatch.setattr(
            "djsupport.operational_store.apsw.platform.win32_ver",
            lambda: (
                release_label,
                "10.0.26100",
                "",
                "Multiprocessor Free",
            ),
        )
        monkeypatch.setattr(
            "djsupport.operational_store.apsw.platform.release",
            lambda: release_label,
        )
        monkeypatch.setattr(
            "djsupport.operational_store.apsw.platform.machine",
            lambda: "AMD64",
        )
        manifest = deepcopy(active_upstream_manifest())
        entry = manifest["entries"][0]
        entry["selectors"]["python"] = {
            "implementation": "CPython",
            "version": ".".join(str(part) for part in python_version),
            "abi": python_abi,
            "gil_mode": "gil",
        }
        entry["selectors"]["platform"] = {
            "os": "Windows",
            "version": "10.0.26100",
            "kernel_release": release_label,
            "product_type": "server",
            "architecture": "AMD64",
        }
        entry["artifact"]["platform_tag"] = python_abi
        entry["artifact"]["build"]["runner_image"] = {
            "label": "windows-2025",
            "version": "20260815.1",
            "manifest_url": "https://runner.example/windows-2025",
        }
        entry["selectors"]["binding"]["extension_sha256"] = (
            "dda3dd1718606f115a90df359bd0993d674ef383eb995a52a995dc6f86641c26"
        )
        entry["selectors"]["sqlite"]["compile_options_sha256"] = (
            "e6bdc0de01d63b4910162c1847d37db5af394866c14ee461b1ce83920bf4ffd4"
        )

        facts = probe_apsw_runtime()
        result = SQLiteRuntimeQualification(manifest).classify(facts)
        near_miss = SQLiteRuntimeQualification(manifest).classify(
            replace(facts, os_version="10.0.19045")
        )
        same_build_workstation = SQLiteRuntimeQualification(
            manifest
        ).classify(replace(facts, os_product_type="workstation"))

        assert facts.os_version == "10.0.26100"
        assert facts.os_product_type == "server"
        assert result.state is QualificationState.QUALIFIED_UPSTREAM
        assert near_miss.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert near_miss.reason_code == "platform_unapproved"
        assert same_build_workstation.state is (
            QualificationState.UNQUALIFIED_UNKNOWN
        )
        assert same_build_workstation.reason_code == "platform_unapproved"

    def test_unavailable_binding_fails_closed_without_echoing_import_details(
        self,
        monkeypatch,
    ):
        private_value = "/Users/example/private/apsw.so"

        def unavailable(name):
            raise ModuleNotFoundError(private_value)

        monkeypatch.setattr(
            "djsupport.operational_store.apsw.import_module",
            unavailable,
        )
        qualification = SQLiteRuntimeQualification.packaged()

        result = qualification.classify_installed()

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "binding_unavailable"
        assert private_value not in repr(result.diagnostic)

    def test_probe_exception_does_not_chain_private_import_details(
        self,
        monkeypatch,
    ):
        private_value = "/Users/example/private/apsw.so"

        def unavailable(name):
            raise ModuleNotFoundError(private_value)

        monkeypatch.setattr(
            "djsupport.operational_store.apsw.import_module",
            unavailable,
        )

        with pytest.raises(RuntimeProbeError) as caught:
            probe_apsw_runtime()

        assert private_value not in str(caught.value)
        assert caught.value.__cause__ is None

    def test_incomplete_binding_installation_fails_closed(
        self,
        monkeypatch,
        tmp_path,
    ):
        configure_synthetic_probe(monkeypatch, tmp_path)
        private_value = "/Users/example/private/site-packages"

        def unavailable(name):
            raise ModuleNotFoundError(private_value)

        monkeypatch.setattr(
            "djsupport.operational_store.apsw.distribution_version",
            unavailable,
        )

        result = SQLiteRuntimeQualification.packaged().classify_installed()

        assert result.state is QualificationState.UNQUALIFIED_UNKNOWN
        assert result.reason_code == "runtime_facts_unavailable"
        assert private_value not in repr(result.diagnostic)


class TestRuntimeGate:
    def test_rejected_runtime_stops_before_a_store_path_is_created(
        self,
        monkeypatch,
        tmp_path,
    ):
        private_path = tmp_path / "operational-store.sqlite3"
        facts = replace(
            qualified_runtime_facts(),
            binding_extension_sha256="d" * 64,
        )
        monkeypatch.setattr(
            "djsupport.operational_store.apsw.probe_apsw_runtime",
            lambda: facts,
        )
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())

        with pytest.raises(
            SQLiteRuntimeUnavailable,
            match="binding_artifact_unapproved",
        ):
            qualification.run_qualified(
                lambda evidence: private_path.touch(),
            )

        assert not private_path.exists()

    def test_exactly_qualified_runtime_can_enter_the_store_operation(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "djsupport.operational_store.apsw.probe_apsw_runtime",
            qualified_runtime_facts,
        )
        qualification = SQLiteRuntimeQualification(active_upstream_manifest())

        evidence_id = qualification.run_qualified(
            lambda evidence: evidence.evidence_id,
        )

        assert evidence_id == "apsw/3.53.4.0/test-wheel"


class TestBindingArchitecture:
    def test_operational_store_has_one_direct_sqlite_binding_import(self):
        repository_root = Path(__file__).parents[1]
        package_root = repository_root / "djsupport" / "operational_store"
        apsw_importers = set()
        sqlite3_importers = set()

        for path in package_root.rglob("*.py"):
            relative_path = path.relative_to(repository_root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "apsw":
                            apsw_importers.add(relative_path)
                        if alias.name == "sqlite3":
                            sqlite3_importers.add(relative_path)
                if isinstance(node, ast.ImportFrom):
                    if node.module == "apsw":
                        apsw_importers.add(relative_path)
                    if node.module == "sqlite3":
                        sqlite3_importers.add(relative_path)
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "import_module"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "apsw"
                ):
                    apsw_importers.add(relative_path)

        assert apsw_importers == {"djsupport/operational_store/apsw.py"}
        assert not sqlite3_importers
