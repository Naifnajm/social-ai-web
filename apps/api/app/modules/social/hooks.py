"""Extension points of publishing, filled by other features at import time (in their own module).

    from app.modules.social import hooks
    hooks.TEXT_FILTERS.append(my_filter)        # (db, post, account, text) -> text   e.g. tracked short links
    hooks.BEFORE_SUBMIT.append(my_check)        # (db, post, user_id, action) -> None | "to_approve"  e.g. approvals
    hooks.AFTER_PUBLISH.append(my_callback)     # (db, post) -> None                  e.g. notify, evergreen
    hooks.POST_LIMIT_CHECKS.append(my_limit)    # (db, workspace_id) -> None (raise LimitReached)  e.g. plans
    hooks.AFTER_CONNECT.append(my_connect)      # (db, accounts) -> None             e.g. subscribe a Page to webhooks
    hooks.DASHBOARD_EXTENDERS.append(my_block)  # (db, workspace_id, data, start, end, prev_start, platform,
                                                #  account_ids) -> None: add keys to the Performance data
                                                #  (e.g. data["kpis"]["link_clicks"], data["extra"]["results"])

The publishing builder calls every function of the matching list at the right moment:
* TEXT_FILTERS — for each account, just before the text is sent (and before its length is checked);
* BEFORE_SUBMIT — in ``service.submit`` for publish / schedule / best_time, after validation; may raise to block;
* AFTER_CONNECT — right after OAuth created / updated accounts (a failure must never block connecting);
* AFTER_PUBLISH — once a publishing run has put the post live on at least one network;
* POST_LIMIT_CHECKS — in ``service.submit`` before a post is published or scheduled (not for drafts or retries).
"""
TEXT_FILTERS: list = []
BEFORE_SUBMIT: list = []
AFTER_PUBLISH: list = []
POST_LIMIT_CHECKS: list = []
AFTER_CONNECT: list = []
DASHBOARD_EXTENDERS: list = []
