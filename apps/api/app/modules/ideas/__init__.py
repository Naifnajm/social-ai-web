"""Ideas of the day: ready-to-publish suggestions built from what works on the workspace's own pages, what
people say about the brand (Radar) and what is rising in its market — a caption per network, a carousel in the
brand's look or a video script, and the best time to post. People edit and approve; the post is then scheduled
(through the approval flow when the workspace uses it) and published automatically.

    from app.modules.ideas import service as ideas
    ideas.generate(db, workspace, user_id, count=4)   # new ContentIdea rows (AI, or rules without AI)
    ideas.approve(db, idea, user_id, ...)             # a scheduled post (or one waiting for approval)
"""
