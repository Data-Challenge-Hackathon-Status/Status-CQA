"""Deterministic metadata aggregation for NEW 1.7.2 assessments only.

Never rewrites scores, claims, evidence or the original provider response.
The engine keeps strict semantic validation after this transformation.
"""
from .contracts import ModelAssessment
from .io import fingerprint

RULE = "append-unverified-claim-limitations-v1"


def aggregate_claim_limitations(assessment: ModelAssessment):
    normalized = assessment.model_copy(deep=True)
    changes = []
    for cid, decision in normalized.criteria.items():
        review = decision.knowledge_review
        if review is None:
            continue
        before = list(decision.limitations)
        added = []
        for claim in review.external_claims:
            # Missing/blank limitations still fail strict validation. Never fabricate text.
            if (claim.status == "unverified" and claim.limitation and claim.limitation.strip()
                    and claim.limitation not in decision.limitations):
                decision.limitations.append(claim.limitation)
                added.append(claim.limitation)
        if added:
            changes.append({"path": ["criteria", cid, "limitations"],
                            "before": before, "after": list(decision.limitations), "added": added})
    audit = {"rule": RULE, "input_assessment_hash": fingerprint(assessment),
             "output_assessment_hash": fingerprint(normalized), "changes": changes,
             "scores_claims_evidence_unchanged": True}
    return normalized, audit
