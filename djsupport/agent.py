"""Harness-neutral, machine-readable client contract for Transfers."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

from djsupport.transfer import (
    BatchPlanRequest,
    QualificationDecision,
    QualificationRequest,
    QualificationStatus,
    SpotifyPlaylistChanged,
    SpotifyPlaylistReviewRequired,
    Transfer,
    TransferAuthorization,
)


AGENT_CONTRACT_VERSION = 2


AgentAuthorization = TransferAuthorization


class FirstTransferAction(str, Enum):
    PREVIEW = "preview"
    QUALIFY = "qualify"
    PUBLISH_AND_LINK = "publish_and_link"
    APPLY = "apply"
    APPROVE = "approve"
    RESUME = "resume"
    ABANDON = "abandon"

    @property
    def needs_spotify_access(self) -> bool:
        return self != FirstTransferAction.ABANDON

    @property
    def publishes(self) -> bool:
        return self in {
            FirstTransferAction.PUBLISH_AND_LINK,
            FirstTransferAction.APPLY,
            FirstTransferAction.APPROVE,
        }


@dataclass(frozen=True)
class FirstTransferGuideRequest:
    """Explicit setup facts for the first Rekordbox Transfer guide."""

    spotify_configured: bool = False
    spotify_authenticated: bool = False
    rekordbox_configured: bool = False
    rekordbox_available: bool = False
    playlist_reference: str | None = None
    local_audio_identity: bool | None = None
    action: FirstTransferAction | str | None = None
    transfer_id: str | None = None
    draft_id: str | None = None


def _loopback_review_origin(value: str) -> str:
    """Accept only an origin that keeps the private review URL local."""
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Qualification review origin must be loopback") from exc
    del port
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname is None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Qualification review origin must be loopback")
    hostname = parsed.hostname.casefold()
    if hostname != "localhost":
        try:
            if not ipaddress.ip_address(hostname).is_loopback:
                raise ValueError
        except ValueError as exc:
            raise ValueError(
                "Qualification review origin must be loopback"
            ) from exc
    return f"{parsed.scheme}://{parsed.netloc}"


def capability_document(capability_value, audition_value=None) -> dict:
    capability = {
        "available": capability_value.available,
        "algorithm": capability_value.algorithm,
        "algorithm_version": capability_value.algorithm_version,
    }
    if capability_value.reason is not None:
        capability["reason"] = capability_value.reason
    capability.update({
        "default_enabled": False,
        "authority": "approved_match_reuse_only",
        "first_run_discovery": "none_until_explicit_approval",
        "execution_order": "after_retained_knowledge_before_spotify_search",
    })
    audition = {
        "available": bool(
            audition_value is not None and audition_value.available
        ),
        "default_enabled": False,
        "authority": "none",
        "requires_local_audio_identity": False,
        "requires_durable_matching_knowledge": False,
    }
    if audition_value is not None and audition_value.reason is not None:
        audition["reason"] = audition_value.reason
    elif audition_value is None:
        audition["reason"] = "not_configured"
    return {
        "contract_version": AGENT_CONTRACT_VERSION,
        "phase": "capability",
        "status": "ready",
        "capabilities": {
            "local_audio_identity": capability,
            "local_audio_audition": audition,
        },
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


def qualification_review_required_document(
    phase: str,
    code: str,
    *,
    draft_id: str | None = None,
    next_actions: list[str] | None = None,
) -> dict:
    """Render an expected, privacy-safe Qualification stop condition."""
    document = {
        "contract_version": AGENT_CONTRACT_VERSION,
        "phase": phase,
        "status": "review_required",
        "review": {"code": code},
        "next_actions": next_actions or ["review"],
    }
    if draft_id is not None:
        document["draft_id"] = draft_id
    return document


class AgentTransferContract:
    """Render public Transfer behavior for AI and automation clients."""

    def __init__(self, transfer: Transfer) -> None:
        self._transfer = transfer

    def capabilities(self) -> dict:
        return capability_document(
            self._transfer.local_audio_capability(),
            self._transfer.local_audition_capability(),
        )

    def first_rekordbox_transfer(
        self,
        request: FirstTransferGuideRequest,
        authorization: AgentAuthorization,
    ) -> dict:
        """Return the next safe decision in a first Rekordbox journey."""
        if not request.spotify_configured:
            next_action = "configure_spotify"
            required_input = {
                "kind": "spotify_configuration",
                "redirect_uri": "http://127.0.0.1:8888/callback",
                "callback_policy": "add_without_replacing_existing",
            }
        elif not request.spotify_authenticated:
            next_action = "authenticate_spotify"
            required_input = {"kind": "spotify_authentication"}
        elif not request.rekordbox_configured:
            next_action = "select_rekordbox_xml"
            required_input = {
                "kind": "rekordbox_xml", "selection": "exact_file",
            }
        elif not request.rekordbox_available:
            next_action = "repair_rekordbox_xml"
            required_input = {
                "kind": "rekordbox_xml", "selection": "exact_file",
            }
        elif request.playlist_reference is None:
            next_action = "select_playlist"
            required_input = {
                "kind": "rekordbox_playlist",
                "selection": "one_explicit_playlist",
                "whole_library": False,
            }
        elif request.local_audio_identity is None:
            capability = self._transfer.local_audio_capability()
            return {
                "contract_version": AGENT_CONTRACT_VERSION,
                "phase": "first_rekordbox_transfer",
                "status": "decision_required",
                "next_action": "choose_local_audio_identity",
                "required_input": {"kind": "boolean", "default": False},
                "local_audio_identity": {
                    "available": capability.available,
                    "scope": "selected_tracks_only",
                    "uploads": "none",
                    "file_changes": "none",
                    "first_run_spotify_search_reduction": False,
                    "future_reuse": "exact_approved_match_after_approval",
                    "approval_authority": "none",
                    "audition": "separate",
                },
            }
        elif (
            request.local_audio_identity
            and not self._transfer.local_audio_capability().available
        ):
            return {
                "contract_version": AGENT_CONTRACT_VERSION,
                "phase": "first_rekordbox_transfer",
                "status": "decision_required",
                "next_action": "continue_without_local_audio_identity",
                "required_input": {"kind": "boolean", "value": False},
                "reason": {"code": "local_audio_identity_unavailable"},
            }
        elif not authorization.private_source:
            return {
                "contract_version": AGENT_CONTRACT_VERSION,
                "phase": "first_rekordbox_transfer",
                "status": "authorization_required",
                "next_action": "authorize_private_source",
                "required_authorization": "private_source",
            }
        else:
            try:
                action = (
                    FirstTransferAction(request.action)
                    if request.action is not None else None
                )
            except ValueError:
                return {
                    "contract_version": AGENT_CONTRACT_VERSION,
                    "phase": "first_rekordbox_transfer",
                    "status": "error",
                    "error": {"code": "unsupported_action"},
                    "next_action": "review_request",
                }
            batch_request = BatchPlanRequest(
                playlist_references=(request.playlist_reference,),
                preview=True,
                local_audio_identity=request.local_audio_identity,
            )
            if action == FirstTransferAction.RESUME:
                if request.transfer_id is None:
                    raise ValueError("Resume requires a Transfer identity")
                outcome = self.execute_batch(
                    batch_request, authorization,
                    transfer_id=request.transfer_id,
                )
                return self._first_guide_step(outcome, default_action="qualify")
            if action == FirstTransferAction.ABANDON:
                if request.transfer_id is None:
                    raise ValueError("Abandonment requires a Transfer identity")
                self._transfer.abandon(request.transfer_id)
                return {
                    "contract_version": AGENT_CONTRACT_VERSION,
                    "phase": "first_rekordbox_transfer",
                    "status": "abandoned",
                    "transfer_id": request.transfer_id,
                    "next_action": None,
                }
            if action == FirstTransferAction.APPROVE:
                if request.draft_id is None:
                    raise ValueError(
                        "Approval requires a Qualification Draft identity"
                    )
                progress = self.qualification_progress(
                    request.draft_id, authorization,
                )
                progress_actions = progress.get("next_actions", [])
                if (
                    progress.get("status") != "approved"
                    and (
                        not progress_actions
                        or progress_actions[0] != "approve"
                    )
                ):
                    return self._first_guide_step(progress)
                approved = self.approve_qualification(
                    request.draft_id, authorization,
                )
                next_actions = approved.pop("next_actions", None) or []
                if "counts" not in approved:
                    approved["next_actions"] = next_actions
                    return self._first_guide_step(approved)
                counts = approved["counts"]
                approved.update({
                    "phase": "first_rekordbox_transfer",
                    "effects": {
                        "spotify_writes_during_approval": 0,
                        "spotify_playlist_items": counts["approved"],
                    },
                    "retained": {
                        "approved_matches": counts["approved"],
                        "corrections": counts["corrections"],
                        "rejected_matches": counts["rejected"],
                    },
                    "next_action": None,
                })
                return approved
            if action == FirstTransferAction.APPLY:
                if request.draft_id is None:
                    raise ValueError(
                        "Draft application requires a Qualification identity"
                    )
                progress = self.qualification_progress(
                    request.draft_id, authorization,
                )
                progress_actions = progress.get("next_actions", [])
                if (
                    progress.get("status") == "approved"
                    or not progress_actions
                    or progress_actions[0] not in {"apply", "approve"}
                ):
                    return self._first_guide_step(progress)
                if (
                    progress_actions[0] == "approve"
                    and not authorization.spotify_write
                ):
                    return self._first_guide_step(progress)
                if not authorization.spotify_write:
                    return {
                        "contract_version": AGENT_CONTRACT_VERSION,
                        "phase": "first_rekordbox_transfer",
                        "status": "authorization_required",
                        "draft_id": request.draft_id,
                        "authority": "none",
                        "next_action": "authorize_spotify_write",
                        "required_authorization": "spotify_write",
                    }
                applied = self.apply_qualification(
                    request.draft_id, authorization,
                )
                return self._first_guide_step(applied)
            if action == FirstTransferAction.PUBLISH_AND_LINK:
                if request.draft_id is None:
                    raise ValueError(
                        "Publication requires a Qualification Draft identity"
                    )
                progress = self.qualification_progress(
                    request.draft_id, authorization,
                )
                progress_actions = progress.get("next_actions", [])
                if not progress_actions or progress_actions[0] != "publish_and_link":
                    return self._first_guide_step(progress)
                if not authorization.spotify_write:
                    return {
                        "contract_version": AGENT_CONTRACT_VERSION,
                        "phase": "first_rekordbox_transfer",
                        "status": "authorization_required",
                        "draft_id": request.draft_id,
                        "authority": "none",
                        "next_action": "authorize_spotify_write",
                        "required_authorization": "spotify_write",
                    }
                publishing_request = BatchPlanRequest(
                    playlist_references=(request.playlist_reference,),
                    preview=False,
                    local_audio_identity=request.local_audio_identity,
                )
                published = self.execute_batch(
                    publishing_request, authorization,
                )
                if published.get("status") != "completed":
                    return self._first_guide_step(published)
                linked = self.link_qualification(
                    request.draft_id, published["transfer_id"], authorization,
                )
                return self._first_guide_step(linked)
            if request.draft_id is not None and action is None:
                qualification = self.qualification_progress(
                    request.draft_id, authorization,
                )
                next_actions = qualification.get("next_actions", [])
                if not next_actions:
                    return self._first_guide_step(qualification)
                primary_action = next_actions[0]
                if (
                    primary_action in {"publish_and_link", "apply"}
                    and not authorization.spotify_write
                ):
                    return {
                        "contract_version": AGENT_CONTRACT_VERSION,
                        "phase": "first_rekordbox_transfer",
                        "status": "authorization_required",
                        "draft_id": request.draft_id,
                        "authority": "none",
                        "next_action": "authorize_spotify_write",
                        "required_authorization": "spotify_write",
                    }
                return self._first_guide_step(qualification)
            if request.transfer_id is not None and action is None:
                progress = self.progress(request.transfer_id, authorization)
                return self._first_guide_step(progress)
            if action == FirstTransferAction.QUALIFY:
                if request.transfer_id is None:
                    raise ValueError("Qualification requires a Transfer identity")
                qualification = self.qualification_draft(
                    QualificationRequest(
                        transfer_id=request.transfer_id,
                        playlist_reference=request.playlist_reference,
                        include_all=True,
                    ),
                    authorization,
                )
                return self._first_guide_step(qualification)
            if action == FirstTransferAction.PREVIEW:
                outcome = self.execute_batch(batch_request, authorization)
                return self._first_guide_step(
                    outcome, default_action="qualify",
                )
            plan_document = self.plan_batch(batch_request, authorization)
            plan_document.pop("next_actions", None)
            plan_document.update({
                "phase": "first_rekordbox_transfer",
                "next_action": "preview",
                "required_input": {
                    "kind": "action_confirmation", "action": "preview",
                },
            })
            return plan_document
        return {
            "contract_version": AGENT_CONTRACT_VERSION,
            "phase": "first_rekordbox_transfer",
            "status": "input_required",
            "next_action": next_action,
            "required_input": required_input,
        }

    @staticmethod
    def _first_guide_step(
        document: dict, *, default_action: str | None = None,
    ) -> dict:
        """Render one truthful primary action from an existing policy result."""
        actions = document.pop("next_actions", None) or []
        next_action = actions[0] if actions else default_action
        document.update({
            "phase": "first_rekordbox_transfer",
            "next_action": next_action,
        })
        if next_action is None:
            document.pop("required_input", None)
        elif next_action == "review" and document.get("review_url"):
            document["required_input"] = {
                "kind": "local_qualification_review",
                "review_url": document["review_url"],
            }
        elif next_action == "approve":
            document["required_input"] = {
                "kind": "authority_confirmation",
                "authority": "playlist_approval",
            }
        else:
            document["required_input"] = {
                "kind": "action_confirmation", "action": next_action,
            }
        return document

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
                *(
                    ["local_audio_identity"]
                    if request.local_audio_identity else []
                ),
                *(
                    ["local_audio_audition"]
                    if request.local_audio_audition else []
                ),
                *([] if request.preview else ["spotify_write"]),
            ],
            "local_audio": {
                "identity_requested": request.local_audio_identity,
                "audition_requested": request.local_audio_audition,
                "identity_default_enabled": False,
                "identity_first_run_discovery": "none_until_explicit_approval",
                "identity_execution_order": (
                    "after_retained_knowledge_before_spotify_search"
                ),
                "audition_requires_identity": False,
            },
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
        try:
            report = self._transfer.execute_batch(plan, transfer_id=batch_id)
        except SpotifyPlaylistReviewRequired:
            return {
                "contract_version": AGENT_CONTRACT_VERSION,
                "phase": "execute",
                "status": "review_required",
                "batch_id": plan_result["batch_id"],
                "review": {"code": "source_selection_changed"},
                "required_authorizations": [],
                "next_actions": ["replan"],
            }
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
                ["resume"] if status == "paused" else ["qualify"]
            ),
        }

    def qualification_draft(
        self,
        request: QualificationRequest,
        authorization: AgentAuthorization,
        *,
        review_origin: str = "http://127.0.0.1:8000",
    ) -> dict:
        """Obtain a draft while keeping source and playlist facts local."""
        required = self._transfer.private_source_authorization_requirement(
            authorization,
        )
        if required:
            return authorization_required_document("qualification", required)
        review_origin = _loopback_review_origin(review_origin)
        try:
            view = self._transfer.obtain_qualification(request, authorization)
        except SpotifyPlaylistChanged:
            return qualification_review_required_document(
                "qualification", "spotify_playlist_changed",
            )
        except SpotifyPlaylistReviewRequired as exc:
            return qualification_review_required_document(
                "qualification", "qualification_review_required",
                draft_id=exc.draft_id,
                next_actions=["review", "discard"],
            )
        return self._qualification_document(view, review_origin)

    def qualification_progress(
        self,
        draft_id: str,
        authorization: AgentAuthorization,
        *,
        review_origin: str = "http://127.0.0.1:8000",
    ) -> dict:
        required = self._transfer.private_source_authorization_requirement(
            authorization,
        )
        if required:
            return authorization_required_document("qualification", required)
        review_origin = _loopback_review_origin(review_origin)
        try:
            view = self._transfer.qualification(draft_id, authorization)
        except SpotifyPlaylistChanged:
            return qualification_review_required_document(
                "qualification", "spotify_playlist_changed",
                draft_id=draft_id,
                next_actions=["review", "discard"],
            )
        except SpotifyPlaylistReviewRequired:
            return qualification_review_required_document(
                "qualification", "qualification_review_required",
                draft_id=draft_id,
                next_actions=["review", "discard"],
            )
        return self._qualification_document(view, review_origin)

    def record_qualification(
        self,
        draft_id: str,
        item_id: str,
        decision: QualificationDecision,
        authorization: AgentAuthorization,
        *,
        spotify_reference: str | None = None,
        reason: str | None = None,
        exclude: bool = False,
        review_origin: str = "http://127.0.0.1:8000",
    ) -> dict:
        """Stage one opaque draft outcome through the public Transfer seam."""
        required = self._transfer.private_source_authorization_requirement(
            authorization,
        )
        if required:
            return authorization_required_document(
                "qualification_decision", required,
            )
        review_origin = _loopback_review_origin(review_origin)
        try:
            view = self._transfer.record_qualification(
                draft_id,
                item_id,
                decision,
                authorization,
                spotify_reference=spotify_reference,
                reason=reason,
                exclude=exclude,
            )
        except SpotifyPlaylistChanged:
            return qualification_review_required_document(
                "qualification_decision", "spotify_playlist_changed",
                draft_id=draft_id,
                next_actions=["review", "discard"],
            )
        except SpotifyPlaylistReviewRequired:
            return qualification_review_required_document(
                "qualification_decision", "qualification_review_required",
                draft_id=draft_id,
                next_actions=["review", "discard"],
            )
        return self._qualification_document(view, review_origin)

    @staticmethod
    def _qualification_document(view, review_origin: str) -> dict:
        review_origin = _loopback_review_origin(review_origin)
        status = view.status.value
        return {
            "contract_version": AGENT_CONTRACT_VERSION,
            "phase": "qualification",
            "status": status,
            "draft_id": view.draft_id,
            "transfer_id": view.transfer_id,
            "counts": {
                "items": len(view.items),
                "pending": view.pending,
                "deferred": view.deferred,
            },
            "authority": "none",
            "current_item": (
                {
                    "item_id": view.current_item.item_id,
                    "permitted_actions": [
                        action.value
                        for action in view.current_item.permitted_actions
                    ],
                }
                if view.current_item is not None else None
            ),
            "review_url": (
                f"{review_origin.rstrip('/')}/qualification/{view.draft_id}"
            ),
            "next_actions": list(view.next_actions),
        }

    def link_qualification(
        self,
        draft_id: str,
        publishing_transfer_id: str,
        authorization: AgentAuthorization,
        *,
        review_origin: str = "http://127.0.0.1:8000",
    ) -> dict:
        required = self._transfer.private_source_authorization_requirement(
            authorization,
        )
        if required:
            return authorization_required_document(
                "qualification_link", required,
            )
        review_origin = _loopback_review_origin(review_origin)
        try:
            view = self._transfer.link_qualification(
                draft_id, publishing_transfer_id, authorization,
            )
        except SpotifyPlaylistChanged:
            return qualification_review_required_document(
                "qualification_link", "spotify_playlist_changed",
                draft_id=draft_id,
                next_actions=["review", "discard"],
            )
        except SpotifyPlaylistReviewRequired:
            return qualification_review_required_document(
                "qualification_link", "qualification_review_required",
                draft_id=draft_id,
                next_actions=["review", "discard"],
            )
        return self._qualification_document(view, review_origin)

    def apply_qualification(
        self, draft_id: str, authorization: AgentAuthorization,
    ) -> dict:
        required = self._transfer.private_source_authorization_requirement(
            authorization,
        )
        if required:
            return authorization_required_document("qualification_apply", required)
        if not authorization.spotify_write:
            return authorization_required_document(
                "qualification_apply", "spotify_write",
            )
        try:
            outcome = self._transfer.apply_qualification(draft_id, authorization)
        except SpotifyPlaylistChanged:
            return qualification_review_required_document(
                "qualification_apply", "spotify_playlist_changed",
                draft_id=draft_id,
                next_actions=["review", "discard"],
            )
        except SpotifyPlaylistReviewRequired:
            return qualification_review_required_document(
                "qualification_apply", "qualification_review_required",
                draft_id=draft_id,
                next_actions=["review", "discard"],
            )
        return {
            "contract_version": AGENT_CONTRACT_VERSION,
            "phase": "qualification_apply",
            "status": outcome.status.value,
            "draft_id": outcome.draft_id,
            "counts": {"applied_items": outcome.applied_items},
            "authority": "none",
            "next_actions": list(outcome.next_actions),
        }

    def discard_qualification(
        self, draft_id: str, authorization: AgentAuthorization,
    ) -> dict:
        required = self._transfer.private_source_authorization_requirement(
            authorization,
        )
        if required:
            return authorization_required_document(
                "qualification_discard", required,
            )
        view = self._transfer.discard_qualification(draft_id, authorization)
        return {
            "contract_version": AGENT_CONTRACT_VERSION,
            "phase": "qualification_discard",
            "status": view.status.value,
            "draft_id": view.draft_id,
            "authority": "none",
            "next_actions": list(view.next_actions),
        }

    def supersede_qualification(
        self,
        draft_id: str,
        authorization: AgentAuthorization,
        *,
        review_origin: str = "http://127.0.0.1:8000",
    ) -> dict:
        required = self._transfer.private_source_authorization_requirement(
            authorization,
        )
        if required:
            return authorization_required_document(
                "qualification_supersede", required,
            )
        review_origin = _loopback_review_origin(review_origin)
        try:
            view = self._transfer.supersede_qualification(
                draft_id, authorization,
            )
        except SpotifyPlaylistReviewRequired:
            return qualification_review_required_document(
                "qualification_supersede", "qualification_review_required",
                draft_id=draft_id,
                next_actions=["review"],
            )
        return self._qualification_document(view, review_origin)

    def approve_qualification(
        self, draft_id: str, authorization: AgentAuthorization,
    ) -> dict:
        required = self._transfer.private_source_authorization_requirement(
            authorization,
        )
        if required:
            return authorization_required_document(
                "qualification_approval", required,
            )
        try:
            outcome = self._transfer.approve_qualification(
                draft_id, authorization,
            )
        except SpotifyPlaylistChanged:
            return qualification_review_required_document(
                "qualification_approval", "spotify_playlist_changed",
                draft_id=draft_id,
            )
        except SpotifyPlaylistReviewRequired:
            return qualification_review_required_document(
                "qualification_approval", "qualification_review_required",
                draft_id=draft_id,
            )
        return {
            "contract_version": AGENT_CONTRACT_VERSION,
            "phase": "qualification_approval",
            "status": outcome.status.value.replace(" ", "_"),
            "draft_id": draft_id,
            "counts": {
                "approved": outcome.approved_count,
                "rejected": outcome.rejected_count,
                "collisions": outcome.collision_count,
                "corrections": outcome.correction_count,
            },
            "authority": (
                "playlist_approval"
                if outcome.status.value == "approved" else "none"
            ),
            "next_actions": (
                ["review"] if outcome.status.value == "needs review" else []
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
                else ["qualify"]
            ),
        }
