"""Extension points of publishing, filled by other features at import time (in their own module).

    from app.modules.social import hooks
    hooks.TEXT_FILTERS.append(my_filter)        # (db, post, account, text) -> text   e.g. tracked short links
    hooks.BEFORE_SUBMIT.append(my_check)        # (db, post, user_id, action) -> None | "to_approve"  e.g. approvals
    hooks.AFTER_PUBLISH.append(my_callback)     # (db, post) -> None                  e.g. notify, evergreen
    hooks.POST_LIMIT_CHECKS.append(my_limit)    # (db, workspace_id) -> None (raise LimitReached)  e.g. plans

The publishing builder calls every function of the matching list at the right moment.
"""
TEXT_FILTERS: list = []
BEFORE_SUBMIT: list = []
AFTER_PUBLISH: list = []
POST_LIMIT_CHECKS: list = []
