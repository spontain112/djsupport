"""Harness-neutral, machine-readable client contract for Transfers."""

from __future__ import annotations

from djsupport.transfer import (
    BatchPlanRequest,
    Transfer,
    TransferAuthorization,
)


AGENT_CONTRACT_VERSION = 1


AgentAuthorization = TransferAuthorization


def capability_document(capability_value) -> dict:
    capability = {
        "available": capability_value.available,
        "algorithm": capability_value.algorithm,
        "algorithm_version": capability_value.algorithm_version,
    }
    if capability_value.reason is not None:
        capability["reason"] = capability_value.reason
    return {
        "contract_version": AGENT_CONTRACT_VERSION,
        "phase": "capability",
        "status": "ready",
        "capabilities": {"local_audio_identity": capability},
        "next_actions": ["plan"],
    }


def authorization_required_document(phase: str, required: str) -> dict:
    return {
        "contract_version": AGENT_CONTRACT_VERSION,
        "phase": phase,
        "status": "authorization_required",
        "required_authorizations": [required],
        "next_actions": [f"authorize_{required}"],
    }


def error_document(phase: str, code: str) -> dict:
    """Render a privacy-safe machine error without source-derived details."""
    next_action = {
        "private_source_unavailable": "inspect_private_source",
        "durable_knowledge_required": "enable_durable_knowledge",
        "matching_knowledge_unavailable": "repair_matching_knowledge",
        "spotify_authentication_required": "authenticate_spotify",
        "transfer_failed": "inspect_transfer_status",
    }.get(code, "review_error")
    return {
        "contract_version": AGENT_CONTRACT_VERSION,
        "phase": phase,
        "status": "error",
        "error": {"code": code},
        "next_actions": [next_action],
    }


class AgentTransferContract:
    """Render public Transfer behavior for AI and automation clients."""

    def __init__(self, transfer: Transfer) -> None:
        self._transfer = transfer

    def capabilities(self) -> dict:
        return capability_document(self._transfer.local_audio_capability())

    def plan_batch(
        self, request: BatchPlanRequest, authorization: AgentAuthorization,
    ) -> dict:
        required = self._transfer.authorization_requirement(
            request, authorization, phase="plan",
        )
        if required:
            return authorization_required_document("plan", required)
        plan = self._transfer.plan_batch(request)
        return self._plan_document(request, authorization, plan)

    @staticmethod
    def _plan_document(request, authorization, plan) -> dict:
        batch_id = plan.batch_id
        required = list(Transfer.required_authorizations(
            request, authorization, phase="plan",
        ))
        next_actions = []
        if required:
            next_actions.append("authorize_spotify_write")
        next_actions.append("confirm_expensive" if not plan.ready else "execute")
        return {
            "contract_version": AGENT_CONTRACT_VERSION,
            "phase": "plan",
            "status": "confirmation_required" if not plan.ready else "ready",
            "batch_id": batch_id,
            "confirmation_required": plan.confirmation_required,
            "counts": {
                "playlists": len(plan.playlists),
                "tracks": plan.total_tracks,
                "approved_match_hits": plan.approved_match_hits,
                "retained_proposal_hits": plan.cache_hits,
                "expected_spotify_lookups": plan.expected_uncached_lookups,
                "local_audio_eligible": plan.local_audio_eligible,
                "local_audio_indexed": plan.local_audio_indexed,
                "local_audio_pending": plan.local_audio_pending,
                "local_audio_unavailable": plan.local_audio_unavailable,
            },
            "requested_effects": [
                "private_source",
                *([] if request.preview else ["spotify_write"]),
            ],
            "required_authorizations": required,
            "next_actions": next_actions,
        }

    def execute_batch(
        self, request: BatchPlanRequest, authorization: AgentAuthorization,
        *, transfer_id: str | None = None,
    ) -> dict:
        required = self._transfer.authorization_requirement(
            request, authorization, phase="plan",
        )
        if required:
            return authorization_required_document("execute", required)
        plan = self._transfer.plan_batch(request)
        plan_result = self._plan_document(request, authorization, plan)
        required = self._transfer.authorization_requirement(
            request, authorization, phase="execute",
        )
        if required:
            return {
                **authorization_required_document("execute", required),
                "batch_id": plan_result["batch_id"],
            }
        if not plan.ready:
            return {
                "contract_version": AGENT_CONTRACT_VERSION,
                "phase": "execute",
                "status": "confirmation_required",
                "batch_id": plan_result["batch_id"],
                "required_authorizations": [],
                "next_actions": ["confirm_expensive"],
            }
        batch_id = transfer_id or plan_result["batch_id"]
        report = self._transfer.execute_batch(plan, transfer_id=batch_id)
        status = report.status.replace(" ", "_")
        return {
            "contract_version": AGENT_CONTRACT_VERSION,
            "phase": "outcome",
            "status": status,
            "batch_id": plan_result["batch_id"],
            "transfer_id": report.transfer_id,
            "counts": {
                "playlists": len(report.playlists),
                "matched": report.total_matched,
                "unmatched": report.total_unmatched,
                "spotify_api_lookups": sum(
                    playlist.api_lookups for playlist in report.playlists
                ),
                "local_audio_eligible": sum(
                    playlist.local_audio_eligible for playlist in report.playlists
                ),
                "local_audio_observed": sum(
                    playlist.local_audio_observed for playlist in report.playlists
                ),
                "local_audio_unavailable": sum(
                    playlist.local_audio_unavailable for playlist in report.playlists
                ),
                "local_audio_reused": sum(
                    playlist.local_audio_reused for playlist in report.playlists
                ),
            },
            "required_authorizations": [],
            "next_actions": (
                ["resume"] if status == "paused" else ["review"]
            ),
        }

    def progress(
        self, transfer_id: str, authorization: AgentAuthorization,
    ) -> dict:
        required = self._transfer.private_source_authorization_requirement(
            authorization,
        )
        if required:
            return authorization_required_document("progress", required)
        progress = self._transfer.batch_progress(transfer_id)
        status = progress.status.value.replace(" ", "_")
        return {
            "contract_version": AGENT_CONTRACT_VERSION,
            "phase": "progress",
            "status": status,
            "transfer_id": transfer_id,
            "counts": {
                "playlists": progress.playlists,
                "completed": progress.completed,
                "failed": progress.failed,
                "pending": progress.pending,
            },
            "next_actions": (
                ["resume"] if status in {"paused", "partial_success"}
                else ["review"]
            ),
        }
