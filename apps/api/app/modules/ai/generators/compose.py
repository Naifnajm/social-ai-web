"""Local media helpers used by the generators (no AI): image fitting with Pillow, audio extraction with ffmpeg."""
import io
import os
import shutil
import subprocess
import tempfile

from PIL import Image, ImageOps

from app.core.http import ApiError

SIZES = {"1:1": (1080, 1080), "4:5": (1080, 1350), "9:16": (1080, 1920), "16:9": (1920, 1080)}
EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "video/mp4": ".mp4",
       "video/quicktime": ".mov", "video/webm": ".webm", "audio/mpeg": ".mp3", "audio/wav": ".wav",
       "audio/x-wav": ".wav", "audio/mp4": ".m4a", "audio/ogg": ".ogg"}


def fit_image(content: bytes, width: int, height: int, fmt: str = "PNG") -> bytes:
    """Center-crop and resize an image to exactly ``width``×``height``."""
    image = Image.open(io.BytesIO(content))
    image = ImageOps.exif_transpose(image).convert("RGB")
    image = ImageOps.fit(image, (width, height), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, fmt, quality=92)
    return out.getvalue()


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def _run(args, timeout=600):
    try:
        subprocess.run(args, check=True, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise ApiError("ffmpeg is not installed on the server (apt install ffmpeg).")
    except subprocess.TimeoutExpired:
        raise ApiError("Processing the media took too long.")
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or b"").decode(errors="ignore").strip().splitlines()[-1:] or ["unknown error"]
        raise ApiError("ffmpeg failed: %s" % tail[0][:300])


def extract_audio(content: bytes, mimetype: str) -> bytes:
    """The soundtrack of a video as a small MP3 (speech-to-text services take up to 25 MB)."""
    if not ffmpeg_available():
        raise ApiError("ffmpeg is not installed on the server (apt install ffmpeg).")
    with tempfile.TemporaryDirectory(prefix="sai_") as tmp:
        src = os.path.join(tmp, "in" + EXT.get(mimetype, ".mp4"))
        out = os.path.join(tmp, "out.mp3")
        with open(src, "wb") as fh:
            fh.write(content)
        _run(["ffmpeg", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", out])
        with open(out, "rb") as fh:
            return fh.read()
