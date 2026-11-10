"""Scheduled reports API: schedules CRUD, HTML preview, PDF download, send now (admins)."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.core.deps import Ctx, workspace_ctx
from app.core.errors import AppError, NotFound
from app.core.i18n import _
from app.modules.planning.service import workspace_tz
from app.modules.social.models import SocialAccount
from app.modules.workspaces.models import Role

from . import service as svc
from .models import ReportSchedule

router = APIRouter(prefix="/reports", tags=["reports"])
Period = Literal["last_7", "last_30", "prev_month"]


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    recipients: list[EmailStr] = Field(min_length=1, max_length=30)
    frequency: Literal["weekly", "monthly"] = "weekly"
    weekday: int = Field(default=0, ge=0, le=6, description="0 = Monday")
    month_day: int = Field(default=1, ge=1, le=28)
    hour: int = Field(default=8, ge=0, le=23)
    period: Period = "last_7"
    account_ids: list[int] = []
    language: Literal["ar", "en"] = "ar"
    include_ai: bool = False
    active: bool = True


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    recipients: list[EmailStr] | None = Field(default=None, min_length=1, max_length=30)
    frequency: Literal["weekly", "monthly"] | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    month_day: int | None = Field(default=None, ge=1, le=28)
    hour: int | None = Field(default=None, ge=0, le=23)
    period: Period | None = None
    account_ids: list[int] | None = None
    language: Literal["ar", "en"] | None = None
    include_ai: bool | None = None
    active: bool | None = None


class ScheduleOut(BaseModel):
    id: int
    name: str
    recipients: list[str]
    frequency: str
    weekday: int
    month_day: int
    hour: int
    period: str
    account_ids: list[int]
    language: str
    include_ai: bool
    active: bool
    last_sent_at: datetime | None = None
    next_send_at: datetime | None = None
    last_error: str | None = None
    send_count: int = 0


class ReportsMeta(BaseModel):
    pdf_available: bool
    timezone: str


class SendOut(BaseModel):
    recipients: int
    format: str
    schedule: ScheduleOut


def out(schedule: ReportSchedule) -> ScheduleOut:
    return ScheduleOut(id=schedule.id, name=schedule.name, recipients=list(schedule.recipients or []),
                       frequency=schedule.frequency, weekday=schedule.weekday, month_day=schedule.month_day,
                       hour=schedule.hour, period=schedule.period, account_ids=list(schedule.account_ids or []),
                       language=schedule.language, include_ai=schedule.include_ai, active=schedule.active,
                       last_sent_at=schedule.last_sent_at, next_send_at=schedule.next_send_at,
                       last_error=schedule.last_error, send_count=schedule.send_count or 0)


def get_schedule(ctx: Ctx, schedule_id: int) -> ReportSchedule:
    schedule = ctx.db.get(ReportSchedule, schedule_id)
    if not schedule or schedule.workspace_id != ctx.workspace.id:
        raise NotFound(_("Report not found."))
    return schedule


def _check_accounts(ctx: Ctx, ids: list[int]) -> list[int]:
    if not ids:
        return []
    valid = set(ctx.db.scalars(select(SocialAccount.id).where(SocialAccount.workspace_id == ctx.workspace.id,
                                                              SocialAccount.id.in_(ids))))
    if set(ids) - valid:
        raise NotFound(_("Account not found."))
    return sorted(set(ids))


def _replan(ctx: Ctx, schedule: ReportSchedule) -> None:
    schedule.next_send_at = svc.next_occurrence(schedule, svc.utcnow(), workspace_tz(ctx.workspace)) \
        if schedule.active else None


@router.get("/meta", response_model=ReportsMeta)
def meta(ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    return ReportsMeta(pdf_available=svc.pdf_available(), timezone=ctx.workspace.timezone)


@router.get("/schedules", response_model=list[ScheduleOut])
def list_schedules(ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    rows = ctx.db.scalars(select(ReportSchedule).where(ReportSchedule.workspace_id == ctx.workspace.id)
                          .order_by(ReportSchedule.name, ReportSchedule.id)).all()
    return [out(s) for s in rows]


@router.post("/schedules", response_model=ScheduleOut, status_code=201)
def create_schedule(body: ScheduleIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    data = body.model_dump()
    data["recipients"] = sorted({str(e).lower() for e in body.recipients})
    data["account_ids"] = _check_accounts(ctx, body.account_ids)
    schedule = ReportSchedule(workspace_id=ctx.workspace.id, created_by_id=ctx.user.id, **data)
    _replan(ctx, schedule)
    ctx.db.add(schedule)
    ctx.db.flush()
    return out(schedule)


@router.get("/schedules/{schedule_id}", response_model=ScheduleOut)
def one_schedule(schedule_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    return out(get_schedule(ctx, schedule_id))


@router.patch("/schedules/{schedule_id}", response_model=ScheduleOut)
def update_schedule(schedule_id: int, body: ScheduleUpdate, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    schedule = get_schedule(ctx, schedule_id)
    data = body.model_dump(exclude_unset=True)
    if "recipients" in data:
        data["recipients"] = sorted({str(e).lower() for e in body.recipients or []})
    if "account_ids" in data:
        data["account_ids"] = _check_accounts(ctx, data["account_ids"] or [])
    for key, value in data.items():
        setattr(schedule, key, value)
    if {"frequency", "weekday", "month_day", "hour", "active"} & set(data):
        _replan(ctx, schedule)
    ctx.db.flush()
    return out(schedule)


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    ctx.db.delete(get_schedule(ctx, schedule_id))
    ctx.db.flush()
    return Response(status_code=204)


@router.get("/schedules/{schedule_id}/preview", response_class=HTMLResponse)
def preview_schedule(schedule_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    schedule = get_schedule(ctx, schedule_id)
    return HTMLResponse(svc.render("report.html", svc.schedule_values(ctx.db, schedule)))


@router.get("/preview", response_class=HTMLResponse)
def preview(period: Period = "last_30", language: Literal["ar", "en"] = "ar",
            account_ids: list[int] = Query(default=[]), include_ai: bool = False, title: str | None = None,
            ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """The report for any period without saving a schedule."""
    values = svc.report_values(ctx.db, ctx.workspace, period=period, language=language,
                               account_ids=_check_accounts(ctx, account_ids) or None, include_ai=include_ai,
                               title=(title or "")[:160] or None)
    return HTMLResponse(svc.render("report.html", values))


@router.get("/schedules/{schedule_id}/pdf")
def schedule_pdf(schedule_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    schedule = get_schedule(ctx, schedule_id)
    if not svc.pdf_available():
        raise AppError(_("PDF is not available on this server. Use the preview or send the report: "
                         "it is attached as a web page instead."), code="no_pdf", status_code=409)
    _values, _html, pdf = svc.build(ctx.db, schedule)
    if not pdf:
        raise AppError(_("The PDF could not be created. Please try again."), code="pdf_failed")
    filename = "".join(c if c.isalnum() or c in "-_" else "-" for c in schedule.name)[:60] or "report"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'})


@router.post("/schedules/{schedule_id}/send", response_model=SendOut)
def send_now(schedule_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    schedule = get_schedule(ctx, schedule_id)
    result = svc.send(ctx.db, schedule)
    return SendOut(**result, schedule=out(schedule))
