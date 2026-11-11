"""Make a phone photo of a dish look its best without changing what is on the plate.

    better = enhance_food(Image.open(path))      # same size and content: only light, colour and sharpness change

Classic image processing, no AI: nothing is generated, so the result is still an honest picture of the dish.
Steps: remove the colour cast of indoor light, lift the exposure, add a little contrast and colour, sharpen.
"""
import math

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat


def _lut(curve) -> list[int]:
    return [min(255, max(0, round(curve(level / 255) * 255))) for level in range(256)]


def enhance_food(image: Image.Image, strength: float = 1.0) -> Image.Image:
    """``strength`` 0 returns the photo almost untouched, 1 is the default look, up to 1.5 for very dull photos."""
    strength = min(1.5, max(0.0, strength))
    image = ImageOps.exif_transpose(image).convert("RGB")

    # 1. Colour cast: the brightest part of a food photo is usually something white (the plate, a napkin, foam),
    #    so its colour shows the colour of the light. Pull that toward neutral (limited, and not all the way, so
    #    a dish that fills the frame keeps its own colour), then add a touch of warmth, as food is usually shot.
    luma = image.convert("L")
    histogram = luma.histogram()
    total, seen, bright = sum(histogram), 0, 255
    for bright in range(255, -1, -1):
        seen += histogram[bright]
        if seen >= total * 0.05:
            break
    means = ImageStat.Stat(image, luma.point(lambda v: 255 if v >= bright else 0)).mean
    grey = sum(means) / 3
    gains = [1 + (min(1.5, max(0.7, grey / max(mean, 1))) - 1) * 0.8 * strength for mean in means]
    gains[0] *= 1 + 0.02 * strength
    gains[2] *= 1 - 0.02 * strength
    image = Image.merge("RGB", [band.point(_lut(lambda v, g=gain: v * g)) for band, gain in zip(image.split(), gains)])

    # 2. Exposure: scale so the brightest part of the photo is bright (the white point only: stretching the
    #    black point too would crush a channel that is dark everywhere, such as blue in candle light), then a
    #    gamma that puts the middle of the photo at a pleasant level, blended with a gentle S-curve for contrast.
    histogram = image.convert("L").histogram()
    total, seen, median, white = sum(histogram), 0, 128, 255
    for level, count in enumerate(histogram):
        seen += count
        if seen >= total / 2 and median == 128:
            median = level
        if seen >= total * 0.99:
            white = level
            break
    scale = min(3.0, 255 / max(white, 60))
    middle = min(0.95, max(0.05, median * scale / 255))
    gamma = 1 + (min(1.5, max(0.6, math.log(0.46) / math.log(middle))) - 1) * strength

    def tone(value: float) -> float:
        lifted = min(1.0, value * scale) ** gamma
        return lifted * (1 - 0.25 * strength) + lifted * lifted * (3 - 2 * lifted) * 0.25 * strength

    image = image.point(_lut(tone) * 3)

    # 3. Colour, then sharpness.
    image = ImageEnhance.Color(image).enhance(1 + 0.28 * strength)
    return image.filter(ImageFilter.UnsharpMask(radius=2, percent=int(70 * strength), threshold=2))
