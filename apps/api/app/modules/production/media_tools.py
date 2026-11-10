"""Local media tools of Production (no AI): fitting images with Pillow, merging / reframing / subtitling
videos with ffmpeg (libass shapes Arabic and mixed-direction captions correctly).

Every function takes and returns bytes, so it is easy to test and does not depend on storage.
"""
import io
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache

from PIL import Image, ImageFilter, ImageOps

from app.core.errors import AppError
from app.core.i18n import _

SIZES = {"1:1": (1080, 1080), "4:5": (1080, 1350), "9:16": (1080, 1920), "16:9": (1920, 1080)}
ASPECTS = tuple(SIZES)
EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "video/mp4": ".mp4",
       "video/quicktime": ".mov", "video/webm": ".webm", "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
       "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/aac": ".aac"}


class MediaToolError(AppError):
    pass


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


@lru_cache
def subtitles_available() -> bool:
    """ffmpeg built with libass (the ``subtitles`` filter) is needed to burn captions."""
    if not ffmpeg_available():
        return False
    try:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, timeout=20)
    except Exception:  # pragma: no cover - broken ffmpeg install
        return False
    return b" subtitles " in result.stdout


def _need_ffmpeg() -> None:
    if not ffmpeg_available():
        raise MediaToolError(_("ffmpeg is not installed on the server (apt install ffmpeg)."), code="no_ffmpeg")


def _run(args: list[str], timeout: int = 600, cwd: str | None = None) -> None:
    try:
        subprocess.run(args, check=True, capture_output=True, timeout=timeout, cwd=cwd)
    except FileNotFoundError:
        raise MediaToolError(_("ffmpeg is not installed on the server (apt install ffmpeg)."), code="no_ffmpeg")
    except subprocess.TimeoutExpired:
        raise MediaToolError(_("Processing the media took too long."), code="media_timeout")
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or b"").decode(errors="ignore").strip().splitlines()[-1:] or ["unknown error"]
        raise MediaToolError(_("ffmpeg failed: {error}", error=tail[0][:300]), code="ffmpeg_failed")


def _write(tmp: str, name: str, content: bytes, mimetype: str) -> str:
    path = os.path.join(tmp, name + EXT.get(mimetype, ".bin"))
    with open(path, "wb") as fh:
        fh.write(content)
    return path


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def aspect_of(width: int | None, height: int | None) -> str | None:
    """The closest network format of a picture size."""
    if not width or not height:
        return None
    ratio = width / height
    return min(SIZES, key=lambda a: abs(SIZES[a][0] / SIZES[a][1] - ratio))


# ---------------------------------------------------------------------------- images
def fit_image(content: bytes, width: int, height: int, fmt: str = "PNG") -> bytes:
    """Center-crop and resize an image to exactly ``width``×``height``."""
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert("RGB")
    image = ImageOps.fit(image, (width, height), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, fmt, quality=92)
    return out.getvalue()


def reframe_image(content: bytes, aspect: str, mode: str = "blur") -> bytes:
    """Fit an image to a network format: ``crop`` fills the frame, ``blur`` keeps the whole picture
    over a blurred copy of itself."""
    width, height = SIZES.get(aspect, SIZES["1:1"])
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert("RGB")
    if mode == "crop":
        result = ImageOps.fit(image, (width, height), Image.LANCZOS)
    else:
        result = ImageOps.fit(image, (width, height), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
        foreground = ImageOps.contain(image, (width, height), Image.LANCZOS)
        result.paste(foreground, ((width - foreground.width) // 2, (height - foreground.height) // 2))
    out = io.BytesIO()
    result.save(out, "PNG")
    return out.getvalue()


# ---------------------------------------------------------------------------- video
def _video_size(aspect: str) -> tuple[int, int]:
    """720p-class output keeps encoding fast and is what the networks re-encode to anyway."""
    width, height = SIZES.get(aspect, SIZES["1:1"])
    return width * 2 // 3 // 2 * 2, height * 2 // 3 // 2 * 2


def reframe_video(content: bytes, mimetype: str, aspect: str, mode: str = "blur") -> bytes:
    _need_ffmpeg()
    width, height = _video_size(aspect)
    with tempfile.TemporaryDirectory(prefix="sai_") as tmp:
        src = _write(tmp, "in", content, mimetype)
        out = os.path.join(tmp, "out.mp4")
        fill = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (width, height, width, height)
        if mode == "crop":
            graph = "[0:v]%s,setsar=1[v]" % fill
        else:
            graph = ("[0:v]%s,boxblur=20:4[bg];[0:v]scale=%d:%d:force_original_aspect_ratio=decrease[fg];"
                     "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]") % (fill, width, height)
        _run(["ffmpeg", "-y", "-i", src, "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-movflags", "+faststart", out])
        return _read(out)


def merge(visual: tuple[bytes, str], audio: list[tuple[bytes, str]], aspect: str | None = None) -> bytes:
    """Combine a video or an image with one or several audio tracks (voices, music, effects mixed with
    ``amix``). Returns MP4 bytes.

    * video + audio → the video with the new soundtrack (cut to the shortest)
    * image + audio → a still-image video as long as the audio
    """
    _need_ffmpeg()
    v_content, v_type = visual
    is_image = v_type.startswith("image/")
    with tempfile.TemporaryDirectory(prefix="sai_") as tmp:
        out = os.path.join(tmp, "out.mp4")
        if is_image:
            width, height = SIZES.get(aspect or "1:1", SIZES["1:1"])
            v_path = os.path.join(tmp, "visual.png")
            with open(v_path, "wb") as fh:
                fh.write(fit_image(v_content, width, height))
        else:
            v_path = _write(tmp, "visual", v_content, v_type)
        a_paths = [_write(tmp, "audio%d" % index, content, mimetype) for index, (content, mimetype) in enumerate(audio)]
        args = ["ffmpeg", "-y"]
        args += ["-loop", "1", "-i", v_path] if is_image else ["-i", v_path]
        for path in a_paths:
            args += ["-i", path]
        if len(a_paths) > 1:
            inputs = "".join("[%d:a]" % (i + 1) for i in range(len(a_paths)))
            args += ["-filter_complex", "%samix=inputs=%d:duration=longest:normalize=0[aout]" % (inputs, len(a_paths)),
                     "-map", "0:v:0", "-map", "[aout]"]
        else:
            args += ["-map", "0:v:0", "-map", "1:a:0"]
        if is_image:
            args += ["-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", "25"]
        else:
            args += ["-c:v", "copy"]
        args += ["-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out]
        _run(args)
        return _read(out)


# ---------------------------------------------------------------------------- captions
def extract_audio(content: bytes, mimetype: str) -> bytes:
    """The soundtrack of a video as a small MP3 (speech-to-text services take up to 25 MB)."""
    _need_ffmpeg()
    with tempfile.TemporaryDirectory(prefix="sai_") as tmp:
        src = _write(tmp, "in", content, mimetype)
        out = os.path.join(tmp, "out.mp3")
        _run(["ffmpeg", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", out])
        return _read(out)


def _srt_time(seconds: float) -> str:
    millis = int(round(max(0.0, float(seconds)) * 1000))
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    secs, millis = divmod(millis, 1000)
    return "%02d:%02d:%02d,%03d" % (hours, minutes, secs, millis)


def _wrap(text: str, width: int = 42) -> str:
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        lines.append(line)
    return "\n".join(lines) if len(lines) <= 2 else "\n".join([lines[0], " ".join(lines[1:])])


def to_srt(segments: list[dict]) -> str:
    """``segments``: list of ``{"start", "end", "text"}`` (seconds) → SRT text."""
    blocks = []
    for index, seg in enumerate((s for s in segments if (s.get("text") or "").strip()), 1):
        blocks.append("%d\n%s --> %s\n%s\n" % (index, _srt_time(seg.get("start") or 0), _srt_time(seg.get("end") or 0),
                                               _wrap(seg["text"].strip())))
    return "\n".join(blocks)


CAPTION_ALIGN = {"bottom": 2, "center": 5, "top": 8}
CAPTION_SIZE = {"s": 13, "m": 17, "l": 23}


def burn_subtitles(content: bytes, mimetype: str, srt: str, position: str = "bottom", size: str = "m",
                   font: str = "DejaVu Sans") -> bytes:
    """Draw the captions onto the video."""
    if not subtitles_available():
        raise MediaToolError(_("This server's ffmpeg cannot draw subtitles (it needs libass)."), code="no_libass")
    style = ("FontName=%s,FontSize=%d,Bold=1,PrimaryColour=&H00FFFFFF,BackColour=&H99000000,"
             "OutlineColour=&H99000000,BorderStyle=3,Outline=6,Shadow=0,Alignment=%d,MarginV=%d") % (
        font, CAPTION_SIZE.get(size, 17), CAPTION_ALIGN.get(position, 2), 28 if position != "center" else 0)
    with tempfile.TemporaryDirectory(prefix="sai_") as tmp:
        src = _write(tmp, "in", content, mimetype)
        with open(os.path.join(tmp, "subs.srt"), "w", encoding="utf-8") as fh:
            fh.write(srt)
        _run(["ffmpeg", "-y", "-i", os.path.basename(src), "-vf",
              "subtitles=subs.srt:charenc=UTF-8:force_style='%s'" % style,
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
              "-c:a", "copy", "-movflags", "+faststart", "out.mp4"], cwd=tmp)
        return _read(os.path.join(tmp, "out.mp4"))
