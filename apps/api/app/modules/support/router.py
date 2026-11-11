"""Support tickets.

For everyone in a workspace:
    POST /api/support/tickets                 write to support (an error's reference and details can be attached)
    GET  /api/support/tickets                 my tickets (admins: every ticket of the workspace)
    GET  /api/support/tickets/{id}            one ticket with its messages
    POST /api/support/tickets/{id}/messages   answer
    POST /api/support/tickets/{id}/close      mark as solved

For platform administrators:
    GET  /api/admin/support/tickets           every ticket, by status, with counts
    GET  /api/admin/support/tickets/{id}      the ticket, the stored error and the workspace's recent failed calls
    POST /api/admin/support/tickets/{id}/messages   answer (the person is notified)
    POST /api/admin/support/tickets/{id}/status     open | answered | closed
    GET  /api/admin/support/errors            latest failures on our side, with or without a ticket
    POST /api/admin/support/test-error        fail on purpose, to check that errors reach this page
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db, utcnow
from app.core.deps import Ctx, superadmin, workspace_ctx
from app.core.errors import AppError, NotFound
from app.core.hardening import rate_limit
from app.core.i18n import _
from app.core.models import ApiLog, ErrorEvent
from app.core.notify import notify
from app.modules.auth.models import User
from app.modules.workspaces.models import Role, Workspace

from .models import CATEGORIES, STATUSES, SupportMessage, SupportTicket

router = APIRouter(tags=["support"])
CONTEXT_KEYS = ("code", "message", "status", "page", "request", "browser", "locale", "app")


# ------------------------------------------------------------------ schemas
class TicketIn(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    category: str = "problem"
    error_ref: str | None = Field(default=None, max_length=12)
    context: dict | None = None


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=8000)


class StatusIn(BaseModel):
    status: str


class MessageOut(BaseModel):
    id: int
    body: str
    staff: bool
    author: str | None = None
    created_at: datetime


class TicketOut(BaseModel):
    id: int
    subject: str
    category: str
    status: str
    error_ref: str | None = None
    unread: bool = False
    author: str | None = None
    created_at: datetime
    last_message_at: datetime
    messages: list[MessageOut] | None = None


class ErrorOut(BaseModel):
    ref: str
    status: int
    code: str
    method: str
    path: str
    message: str
    detail: str | None = None
    workspace: str | None = None
    user: str | None = None
    ticket_id: int | None = None
    created_at: datetime


class FailedCall(BaseModel):
    service: str
    operation: str
    status_code: int | None = None
    error: str | None = None
    created_at: datetime


class AdminTicketOut(TicketOut):
    workspace_id: int
    workspace: str
    email: str | None = None
    context: dict | None = None
    error: ErrorOut | None = None
    failed_calls: list[FailedCall] | None = None


class AdminTicketPage(BaseModel):
    items: list[AdminTicketOut]
    total: int
    counts: dict[str, int]


# ------------------------------------------------------------------ helpers
def _names(db: Session, user_ids: set) -> dict[int, User]:
    ids = {i for i in user_ids if i}
    return {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def _messages(db: Session, ticket: SupportTicket) -> list[MessageOut]:
    users = _names(db, {m.user_id for m in ticket.messages})
    return [MessageOut(id=m.id, body=m.body, staff=m.staff, created_at=m.created_at,
                       author=None if m.staff else getattr(users.get(m.user_id), "name", None))
            for m in ticket.messages]


def _out(db: Session, ticket: SupportTicket, *, full: bool = False) -> TicketOut:
    author = db.get(User, ticket.user_id) if ticket.user_id else None
    return TicketOut(id=ticket.id, subject=ticket.subject, category=ticket.category, status=ticket.status,
                     error_ref=ticket.error_ref, unread=ticket.unread_by_user, author=author.name if author else None,
                     created_at=ticket.created_at, last_message_at=ticket.last_message_at,
                     messages=_messages(db, ticket) if full else None)


def _mine(ctx: Ctx, ticket_id: int) -> SupportTicket:
    ticket = ctx.db.get(SupportTicket, ticket_id)
    if (not ticket or ticket.workspace_id != ctx.workspace.id
            or (ticket.user_id != ctx.user.id and not ctx.can(Role.admin))):
        raise NotFound(_("Ticket not found."))
    return ticket


def _add_message(db: Session, ticket: SupportTicket, user: User, body: str, *, staff: bool) -> None:
    db.add(SupportMessage(ticket_id=ticket.id, user_id=user.id, staff=staff, body=body.strip()))
    ticket.last_message_at = utcnow()
    ticket.status = "answered" if staff else "open"
    ticket.unread_by_user = staff
    db.flush()
    db.refresh(ticket)


def _clean_context(context: dict | None) -> dict | None:
    """Keep the known keys only, as short text: this comes from the browser."""
    if not isinstance(context, dict):
        return None
    out = {key: str(context[key])[:500] for key in CONTEXT_KEYS if context.get(key) not in (None, "")}
    return out or None


# ------------------------------------------------------------------ people of a workspace
@router.post("/support/tickets", response_model=TicketOut, status_code=201,
             dependencies=[Depends(rate_limit("ticket", 10, 3600))])
def create_ticket(data: TicketIn, ctx: Ctx = Depends(workspace_ctx())):
    ticket = SupportTicket(workspace_id=ctx.workspace.id, user_id=ctx.user.id, subject=data.subject.strip(),
                           category=data.category if data.category in CATEGORIES else "problem",
                           error_ref=(data.error_ref or "").strip().upper() or None,
                           context=_clean_context(data.context))
    ctx.db.add(ticket)
    ctx.db.flush()
    _add_message(ctx.db, ticket, ctx.user, data.body, staff=False)
    admins = ctx.db.scalars(select(User.id).where(User.is_superadmin.is_(True), User.is_active.is_(True))).all()
    notify(ctx.db, ctx.workspace.id, list(admins), kind="support.ticket",
           title=_("New support ticket from {workspace}", workspace=ctx.workspace.name), body=ticket.subject,
           link=f"/admin/support?ticket={ticket.id}")
    return _out(ctx.db, ticket, full=True)


@router.get("/support/tickets", response_model=list[TicketOut])
def my_tickets(ctx: Ctx = Depends(workspace_ctx())):
    query = select(SupportTicket).where(SupportTicket.workspace_id == ctx.workspace.id)
    if not ctx.can(Role.admin):
        query = query.where(SupportTicket.user_id == ctx.user.id)
    rows = ctx.db.scalars(query.order_by(SupportTicket.last_message_at.desc()).limit(100)).all()
    return [_out(ctx.db, t) for t in rows]


@router.get("/support/tickets/{ticket_id}", response_model=TicketOut)
def my_ticket(ticket_id: int, ctx: Ctx = Depends(workspace_ctx())):
    ticket = _mine(ctx, ticket_id)
    ticket.unread_by_user = False
    return _out(ctx.db, ticket, full=True)


@router.post("/support/tickets/{ticket_id}/messages", response_model=TicketOut)
def answer(ticket_id: int, data: MessageIn, ctx: Ctx = Depends(workspace_ctx())):
    ticket = _mine(ctx, ticket_id)
    _add_message(ctx.db, ticket, ctx.user, data.body, staff=False)
    return _out(ctx.db, ticket, full=True)


@router.post("/support/tickets/{ticket_id}/close", response_model=TicketOut)
def close(ticket_id: int, ctx: Ctx = Depends(workspace_ctx())):
    ticket = _mine(ctx, ticket_id)
    ticket.status = "closed"
    return _out(ctx.db, ticket, full=True)


# ------------------------------------------------------------------ platform team
def _error_out(db: Session, event: ErrorEvent, *, detail: bool) -> ErrorOut:
    workspace = db.get(Workspace, event.workspace_id) if event.workspace_id else None
    user = db.get(User, event.user_id) if event.user_id else None
    ticket_id = db.scalar(select(SupportTicket.id).where(SupportTicket.error_ref == event.ref).limit(1))
    return ErrorOut(ref=event.ref, status=event.status, code=event.code, method=event.method, path=event.path,
                    message=event.message, detail=event.detail if detail else None,
                    workspace=workspace.name if workspace else None, user=user.name if user else None,
                    ticket_id=ticket_id, created_at=event.created_at)


def _admin_out(db: Session, ticket: SupportTicket, *, full: bool = False) -> AdminTicketOut:
    base = _out(db, ticket, full=full).model_dump()
    workspace = db.get(Workspace, ticket.workspace_id)
    author = db.get(User, ticket.user_id) if ticket.user_id else None
    out = AdminTicketOut(**base, workspace_id=ticket.workspace_id, workspace=workspace.name if workspace else "",
                         email=author.email if author else None, context=ticket.context)
    if full:
        event = db.scalar(select(ErrorEvent).where(ErrorEvent.ref == ticket.error_ref)) if ticket.error_ref else None
        out.error = _error_out(db, event, detail=True) if event else None
        # what failed between this workspace and the networks / AI providers shortly before the ticket
        since = ticket.created_at - timedelta(minutes=30)
        calls = db.scalars(select(ApiLog).where(
            ApiLog.workspace_id == ticket.workspace_id, ApiLog.created_at >= since,
            ApiLog.created_at <= ticket.created_at + timedelta(minutes=1),
            or_(ApiLog.error.is_not(None), ApiLog.status_code >= 400)).order_by(ApiLog.id.desc()).limit(8)).all()
        out.failed_calls = [FailedCall(service=c.service, operation=c.operation, status_code=c.status_code,
                                       error=(c.error or "")[:400] or None, created_at=c.created_at) for c in calls]
    return out


def _ticket(db: Session, ticket_id: int) -> SupportTicket:
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket:
        raise NotFound(_("Ticket not found."))
    return ticket


@router.get("/admin/support/tickets", response_model=AdminTicketPage)
def admin_tickets(status: str | None = None, q: str | None = None, page: int = Query(1, ge=1),
                  page_size: int = Query(25, ge=1, le=100), admin: User = Depends(superadmin),
                  db: Session = Depends(get_db)):
    query = select(SupportTicket)
    if status in STATUSES:
        query = query.where(SupportTicket.status == status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(SupportTicket.subject.ilike(like), SupportTicket.error_ref.ilike(like)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(SupportTicket.last_message_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    counts = dict(db.execute(select(SupportTicket.status, func.count()).group_by(SupportTicket.status)).all())
    return AdminTicketPage(items=[_admin_out(db, t) for t in rows], total=total,
                           counts={s: int(counts.get(s, 0)) for s in STATUSES})


@router.get("/admin/support/tickets/{ticket_id}", response_model=AdminTicketOut)
def admin_ticket(ticket_id: int, admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    return _admin_out(db, _ticket(db, ticket_id), full=True)


@router.post("/admin/support/tickets/{ticket_id}/messages", response_model=AdminTicketOut)
def admin_answer(ticket_id: int, data: MessageIn, admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    ticket = _ticket(db, ticket_id)
    _add_message(db, ticket, admin, data.body, staff=True)
    if ticket.user_id:
        notify(db, ticket.workspace_id, [ticket.user_id], kind="support.reply",
               title=_("Support answered: {subject}", subject=ticket.subject), body=data.body.strip()[:200],
               link=f"/settings/support?ticket={ticket.id}")
    return _admin_out(db, ticket, full=True)


@router.post("/admin/support/tickets/{ticket_id}/status", response_model=AdminTicketOut)
def admin_status(ticket_id: int, data: StatusIn, admin: User = Depends(superadmin), db: Session = Depends(get_db)):
    if data.status not in STATUSES:
        raise AppError(_("Unknown ticket status."), code="bad_status")
    ticket = _ticket(db, ticket_id)
    ticket.status = data.status
    db.flush()
    return _admin_out(db, ticket, full=True)


@router.get("/admin/support/errors", response_model=list[ErrorOut])
def admin_errors(ref: str | None = None, limit: int = Query(30, ge=1, le=100), admin: User = Depends(superadmin),
                 db: Session = Depends(get_db)):
    query = select(ErrorEvent)
    if ref and ref.strip():
        query = query.where(ErrorEvent.ref == ref.strip().upper())
    rows = db.scalars(query.order_by(ErrorEvent.id.desc()).limit(limit)).all()
    return [_error_out(db, event, detail=bool(ref)) for event in rows]


@router.post("/admin/support/test-error", status_code=500)
def admin_test_error(admin: User = Depends(superadmin)):
    """Fails on purpose: the administrator sees the message a customer would see, and the error lands in the list."""
    raise RuntimeError("Test error raised on purpose from the admin support page.")
