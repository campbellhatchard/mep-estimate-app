"""Shared authoring grants for server guards and rendered controls.

READ_ONLY is not a deny override: any assigned authoring role grants access.
Lifecycle restrictions still apply, independently of the user's role.
"""
ESTIMATE_AUTHOR_ROLES = ("ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")
SOW_PREPARE_ROLES = ("ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")


def can_author_estimates(user) -> bool:
    return user.has_role(*ESTIMATE_AUTHOR_ROLES)


def can_edit_estimate(user, revision) -> bool:
    return can_author_estimates(user) and revision.status in ("DRAFT", "REVIEW")


def can_prepare_sow(user) -> bool:
    return user.has_role(*SOW_PREPARE_ROLES)


def can_edit_sow(user, sow) -> bool:
    return can_prepare_sow(user) and sow.status == "DRAFT"
