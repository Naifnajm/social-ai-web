"""Brand kit import from a design system, brand health and AI suggestions (mounted by router.py).

    POST /brand-kits/import/preview      multipart file (.zip/.md/.json/.css) [+ brand_kit_id] -> draft, nothing saved
    GET  /brand-kits/import/{id}/file    one file of the upload (logo / image / font preview; SVG sanitised)
    POST /brand-kits/import/commit       {import_id, brand_kit_id|null, fields, assets, make_default} -> kit + health
    GET  /brand-kits/{id}/completeness   brand health of a kit
    POST /brand-kits/{id}/suggest        {fields: [...]} -> AI suggestions (nothing saved)
    GET  /brand-kits/{id}/fonts          imported font files of the kit;  DELETE …/fonts/{font_id}

The upload waits at most an hour (``BrandImport``, file in the storage folder under ``imports/``).
"""
import secrets
from datetime import timedelta
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.core.config import settings
from app.core.db import utcnow
from app.core.deps import Ctx, workspace_ctx
from app.core.errors import NotFound
from app.core.hardening import UPLOAD_HEADERS
from app.core.i18n import _
from app.core.models import Media
from app.core.storage import save_media
from app.modules.workspaces.models import Role, Workspace

from . import completeness, importer, service, svg
from . import fonts as font_tools
from .models import BrandFont, BrandImport, BrandKit

router = APIRouter(tags=["brand kits"])  # included by router.py under /brand-kits

IMPORT_HOURS = 1
BOOK_FIELDS = ("description", "tagline", "tone", "personality", "audience", "industry", "guidelines", "banned_words",
               "cta", "hashtags", "language_style", "emoji_style", "visual_style", "visual_rules", "sample_posts",
               "photo_style")
KIT_FIELDS = ("name", "color_primary", "color_secondary", "color_accent", "color_text", "color_background",
              "font_heading", "font_family") + BOOK_FIELDS
FONT_MIME = {"woff2": "font/woff2", "woff": "font/woff", "ttf": "font/ttf", "otf": "font/otf"}


# ---------------------------------------------------------------------------- storage of the upload
def _import_path(key: str) -> Path:
    root = Path(settings.storage_dir)
    return root / key


def _cleanup(db) -> None:
    for row in db.scalars(select(BrandImport).where(BrandImport.expires_at < utcnow()).limit(50)):
        _drop(db, row)


def _drop(db, row: BrandImport) -> None:
    try:
        _import_path(row.storage_key).unlink(missing_ok=True)
    except OSError:
        pass
    db.delete(row)
    db.flush()


def _load(ctx: Ctx, token: str) -> BrandImport:
    row = ctx.db.scalar(select(BrandImport).where(BrandImport.token == token,
                                                  BrandImport.workspace_id == ctx.workspace.id))
    if not row or row.expires_at < utcnow():
        raise NotFound(_("This import has expired. Upload the file again."), code="import_expired")
    return row


def _bundle(row: BrandImport) -> dict:
    try:
        content = _import_path(row.storage_key).read_bytes()
    except OSError as exc:
        raise NotFound(_("This import has expired. Upload the file again."), code="import_expired") from exc
    return importer.read_upload(row.filename, content)


# ---------------------------------------------------------------------------- preview
def _facts_from_draft(found: dict, arabic: bool) -> dict:
    return {"fonts": [{"family": f["family"], "has_arabic": f["has_arabic"], "role": f["role"]}
                      for f in found["fonts"] if f["loadable"]], "arabic_needed": arabic}


def build_draft(ctx: Ctx, filename: str, bundle: dict, kit: BrandKit | None) -> dict:
    found = importer.analyse(bundle)
    book, book_source, book_warnings = importer.brand_book(ctx.db, ctx.workspace.id, found.pop("text"),
                                                           user_id=ctx.user.id)
    fields: dict[str, dict] = {}
    if found["name"]:
        fields["name"] = {"value": found["name"], "source": "tokens" if found["has_tokens"] else "readme"}
    elif not kit:
        fields["name"] = {"value": PurePosixPath(filename or "brand").stem[:120] or "Brand", "source": "heuristic"}
    for role in importer.COLOR_ROLES:
        info = found["roles"].get(role)
        if info:
            fields[f"color_{role}"] = {"value": info["value"], "source": info["source"], "token": info["token"]}
    if found["font_heading"]:
        fields["font_heading"] = {"value": found["font_heading"], "source": "tokens"}
    if found["font_body"]:
        fields["font_family"] = {"value": found["font_body"], "source": "tokens"}
    for key, value in book.items():
        fields[key] = {"value": value, "source": book_source}
    current = completeness.kit_values(kit) if kit else {}
    merged = {**current, **{k: v["value"] for k, v in fields.items()}}
    if found["logo_primary"]:
        merged["logo_media_id"] = merged.get("logo_media_id") or -1
    if found["logo_dark"]:
        merged["logo_dark_media_id"] = merged.get("logo_dark_media_id") or -1
    arabic = completeness.arabic_needed(ctx.workspace.locale, merged.get("language_style"))
    facts = _facts_from_draft(found, arabic)
    if kit:
        facts["fonts"] += completeness.kit_facts(ctx.db, kit)["fonts"]
    return {
        "name": found["name"], "fields": fields, "current": {k: current.get(k) for k in KIT_FIELDS} if kit else None,
        "colours": found["colours"], "roles": {k: v["value"] for k, v in found["roles"].items()},
        "families": found["families"], "fonts": found["fonts"], "logos": found["logos"],
        "logo_primary": found["logo_primary"], "logo_dark": found["logo_dark"], "imagery": found["imagery"],
        "docs": found["docs"], "components": found["components"], "ignored": bundle["ignored"],
        "tokens": {"colours": len(found["colours"]), "spacing": found["spacing"], "radius": found["radius"],
                   "shadow": found["shadow"]},
        "book_source": book_source if book else None,
        "warnings": found["warnings"] + book_warnings, "completeness": completeness.report(merged, facts),
        "arabic_needed": arabic,
    }


@router.post("/import/preview")
async def import_preview(file: UploadFile = File(...), brand_kit_id: int | None = Form(default=None),
                         ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """Read a design system and propose a brand kit; nothing is saved to the kit until /import/commit."""
    content = await file.read(importer.MAX_UPLOAD + 1)
    kit = service.get_kit(ctx.db, ctx.workspace.id, brand_kit_id) if brand_kit_id else None
    filename = (file.filename or "upload").replace("\\", "/").split("/")[-1][:255]
    bundle = importer.read_upload(filename, content)
    draft = build_draft(ctx, filename, bundle, kit)
    _cleanup(ctx.db)
    token = secrets.token_urlsafe(24)
    key = f"imports/{ctx.workspace.id}/{token}.bin"
    path = _import_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    row = BrandImport(workspace_id=ctx.workspace.id, token=token, filename=filename, kind=bundle["kind"],
                      size=len(content), storage_key=key, draft=draft, created_by_id=ctx.user.id,
                      expires_at=utcnow() + timedelta(hours=IMPORT_HOURS))
    ctx.db.add(row)
    ctx.db.flush()
    return {"import_id": token, "filename": filename, "kind": bundle["kind"], "brand_kit_id": kit.id if kit else None,
            "expires_at": row.expires_at, **draft}


def _offered(draft: dict) -> dict[str, set]:
    return {"logos": {x["key"] for x in draft.get("logos") or []},
            "imagery": {x["key"] for x in draft.get("imagery") or []},
            "fonts": {x["key"] for x in draft.get("fonts") or [] if x.get("loadable")}}


@router.get("/import/{import_id}/file")
def import_file(import_id: str, key: str, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    row = _load(ctx, import_id)
    offered = _offered(row.draft or {})
    if key not in offered["logos"] | offered["imagery"] | offered["fonts"]:
        raise NotFound(_("File not found."))
    content = _bundle(row)["files"].get(key)
    if content is None:
        raise NotFound(_("File not found."))
    ext = importer._ext(key)
    if ext == "svg":
        content = svg.sanitize(content)
        if content is None:
            raise NotFound(_("File not found."))
    mimetype = importer.IMAGE_MIME.get(ext) or FONT_MIME.get(ext) or "application/octet-stream"
    return Response(content, media_type=mimetype, headers={**UPLOAD_HEADERS, "Cache-Control": "private, max-age=600"})


# ---------------------------------------------------------------------------- commit
class ImportAssets(BaseModel):
    logo: str | None = None
    logo_dark: str | None = None
    logos: list[str] = Field(default_factory=list, max_length=40)
    imagery: list[str] = Field(default_factory=list, max_length=80)
    fonts: list[str] = Field(default_factory=list, max_length=60)


def _commit_fields():
    from .router import BrandKitUpdate
    return BrandKitUpdate


class ImportCommit(BaseModel):
    import_id: str = Field(min_length=8, max_length=60)
    brand_kit_id: int | None = None
    fields: dict = Field(default_factory=dict)
    assets: ImportAssets = Field(default_factory=ImportAssets)
    make_default: bool = False


def _save_asset(ctx: Ctx, files: dict, key: str, tags: list[str]) -> Media | None:
    content = files.get(key)
    if content is None:
        return None
    ext = importer._ext(key)
    name = PurePosixPath(key).name
    if ext == "svg":
        content = svg.sanitize(content)
        if content is None:
            return None
    mimetype = importer.IMAGE_MIME.get(ext) or FONT_MIME.get(ext)
    media = save_media(ctx.db, ctx.workspace.id, content, name, mimetype, source="brand", user_id=ctx.user.id)
    media.tags = tags
    return media


@router.post("/import/commit")
def import_commit(data: ImportCommit, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """Create or update a kit with the values and assets the person chose."""
    from app.modules.billing import limits

    from .router import NULLABLE, kit_out
    row = _load(ctx, data.import_id)
    draft = row.draft or {}
    try:
        values = _commit_fields()(**{k: v for k, v in data.fields.items() if k in KIT_FIELDS}).model_dump(
            exclude_unset=True)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_context=False)) from exc
    offered = _offered(draft)
    chosen = {"logo": [data.assets.logo] if data.assets.logo else [],
              "logo_dark": [data.assets.logo_dark] if data.assets.logo_dark else [],
              "logos": data.assets.logos, "imagery": data.assets.imagery, "fonts": data.assets.fonts}
    for group, keys in chosen.items():
        allowed = offered["fonts"] if group == "fonts" else offered["imagery"] if group == "imagery" else \
            offered["logos"]
        if any(k not in allowed for k in keys):
            raise NotFound(_("File not found."))
    files = _bundle(row)["files"] if any(chosen.values()) else {}
    wanted = {k for keys in chosen.values() for k in keys}
    limits.check(ctx.db, ctx.workspace.id, "storage", amount=sum(len(files.get(k, b"")) for k in wanted))

    kit = service.get_kit(ctx.db, ctx.workspace.id, data.brand_kit_id) if data.brand_kit_id else None
    if kit is None:
        name = values.pop("name", None) or draft.get("name") or PurePosixPath(row.filename).stem[:120] or "Brand"
        kit = BrandKit(workspace_id=ctx.workspace.id, name=name)
        ctx.db.add(kit)
    for key, value in values.items():
        if value is None and key not in NULLABLE:
            continue
        setattr(kit, key, value)
    ctx.db.flush()

    saved: dict[str, Media] = {}
    for group, keys in chosen.items():
        for key in keys:
            if key in saved:
                continue
            tags = ["brand", "font" if group == "fonts" else "logo" if group.startswith("logo") else "imagery"]
            media = _save_asset(ctx, files, key, tags)
            if media:
                saved[key] = media
    if data.assets.logo in saved:
        kit.logo_media_id = saved[data.assets.logo].id
    if data.assets.logo_dark in saved:
        kit.logo_dark_media_id = saved[data.assets.logo_dark].id
    refs = [saved[k].id for k in data.assets.imagery + data.assets.logos if k in saved]
    if refs:
        kit.reference_media_ids = list(dict.fromkeys((kit.reference_media_ids or []) + refs))[:200]
    if data.assets.fonts:
        meta = {f["key"]: f for f in draft.get("fonts") or []}
        heading = font_tools.family_name(kit.font_heading or kit.font_family)
        body = font_tools.family_name(kit.font_family)
        existing = list(ctx.db.scalars(select(BrandFont).where(BrandFont.brand_kit_id == kit.id)))
        for key in data.assets.fonts:
            if key not in saved:
                continue
            info = meta.get(key, {})
            family = str(info.get("family") or PurePosixPath(key).stem)[:120]
            weight, style = int(info.get("weight") or 400), info.get("style") or "normal"
            for old in existing:
                if old.family.lower() == family.lower() and old.weight == weight and old.style == style:
                    ctx.db.delete(old)
            role = "heading" if family.lower() == heading else "body" if family.lower() == body else "other"
            ctx.db.add(BrandFont(workspace_id=ctx.workspace.id, brand_kit_id=kit.id, media_id=saved[key].id,
                                 family=family, weight=weight, style=style, role=role,
                                 has_arabic=info.get("has_arabic")))
    ctx.db.flush()
    if data.make_default or not any(k.is_default for k in service.list_kits(ctx.db, ctx.workspace.id)
                                    if k.id != kit.id):
        service.set_default(ctx.db, kit)
    _drop(ctx.db, row)
    return {"kit": kit_out(kit), "completeness": completeness.for_kit(ctx.db, kit),
            "saved": {"media": len(saved), "fonts": len([k for k in data.assets.fonts if k in saved])}}


# ---------------------------------------------------------------------------- health, suggestions, fonts
@router.get("/{kit_id}/completeness")
def kit_completeness(kit_id: int, ctx: Ctx = Depends(workspace_ctx())):
    return completeness.for_kit(ctx.db, service.get_kit(ctx.db, ctx.workspace.id, kit_id))


SUGGEST_SYSTEM = (
    "You are a senior brand strategist. Complete missing parts of a brand kit so they fit what the kit already "
    "says. Write in the language the kit uses (Arabic by default; natural Arabic, never a translation). Reply with "
    "only one JSON object with only these keys: {keys}. Formats: description (2-3 sentences), tagline (max 80 "
    "characters), tone (2-3 sentences), personality (array of 3-5 single words), audience (1-2 sentences), "
    "industry (a few words), guidelines (array of 4-8 lines starting with ✓ or ✗), banned_words (array), cta "
    "(short), hashtags (array of 3-6), language_style (one of: {languages}), emoji_style (one of: none, light, "
    "rich), visual_style (1-2 sentences usable as an image prompt), visual_rules (array of 3-6 do/don't lines for "
    "visuals starting with ✓ or ✗), sample_posts (array of 2 short posts in the brand's voice), photo_style (object "
    "with some of these keys, values copied exactly from the lists: {camera})."
)


class SuggestIn(BaseModel):
    fields: list[str] = Field(min_length=1, max_length=len(BOOK_FIELDS))


@router.post("/{kit_id}/suggest")
def suggest(kit_id: int, data: SuggestIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """AI suggestions for missing or weak fields (uses AI credit; nothing is saved)."""
    from app.modules.ai import providers
    from app.modules.ai import service as ai

    from .models import LANGUAGE_STYLES
    kit = service.get_kit(ctx.db, ctx.workspace.id, kit_id)
    keys = [k for k in dict.fromkeys(data.fields) if k in BOOK_FIELDS]
    if not keys:
        return {"suggestions": {}}
    system = SUGGEST_SYSTEM.format(keys=", ".join(keys), languages=", ".join(LANGUAGE_STYLES),
                                   camera=importer._camera_lists())
    profile = kit.llm_profile()
    if kit.visual_hint():
        profile += "\n" + kit.visual_hint()
    workspace = ctx.db.get(Workspace, ctx.workspace.id)
    profile += f"\nWorkspace language: {workspace.locale if workspace else 'ar'}"
    fast = providers.fast_model(ctx.db, ctx.workspace.id)
    answer = ai.generate_json(ctx.db, ctx.workspace.id, system, profile, purpose="brand suggestions",
                              model_id=fast.id if fast else None, user_id=ctx.user.id)
    cleaned = importer.clean_book(answer)
    return {"suggestions": {k: v for k, v in cleaned.items() if k in keys}}


@router.get("/{kit_id}/fonts")
def kit_fonts(kit_id: int, ctx: Ctx = Depends(workspace_ctx())):
    kit = service.get_kit(ctx.db, ctx.workspace.id, kit_id)
    rows = ctx.db.scalars(select(BrandFont).where(BrandFont.brand_kit_id == kit.id)
                          .order_by(BrandFont.family, BrandFont.weight))
    return [{"id": f.id, "family": f.family, "weight": f.weight, "style": f.style, "role": f.role,
             "has_arabic": f.has_arabic, "media_id": f.media_id, "url": f"/api/media/{f.media_id}/file"}
            for f in rows]


@router.delete("/{kit_id}/fonts/{font_id}", status_code=204)
def delete_font(kit_id: int, font_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    kit = service.get_kit(ctx.db, ctx.workspace.id, kit_id)
    row = ctx.db.get(BrandFont, font_id)
    if not row or row.brand_kit_id != kit.id:
        raise NotFound(_("File not found."))
    ctx.db.delete(row)
    ctx.db.flush()
