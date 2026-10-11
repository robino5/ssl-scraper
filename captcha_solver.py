import io
import re

from PIL import Image, ImageOps


# microsoft/trocr-small-printed is ~250 MB and accurate enough for the clean
# digit mask below. Switch to "microsoft/trocr-base-printed" if it misreads.
TROCR_MODEL = "microsoft/trocr-small-printed"
CAPTCHA_LENGTH = 4

_processor = None
_model = None


def _load_model():

    global _processor, _model

    if _model is None:
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        from transformers.utils import logging as transformers_logging

        # The checkpoint has no encoder pooler weights; TrOCR never uses the
        # pooler, so the "MISSING encoder.pooler.dense" load report is noise.
        transformers_logging.set_verbosity_error()
        transformers_logging.disable_progress_bar()

        print(f"Loading TrOCR model {TROCR_MODEL} (first run downloads it)...")
        _processor = TrOCRProcessor.from_pretrained(TROCR_MODEL)
        _model = VisionEncoderDecoderModel.from_pretrained(TROCR_MODEL)
        _model.eval()

    return _processor, _model


def preprocess(image):
    """Keep only the white foreground digits as black on white.

    The SSLCOMMERZ CAPTCHA draws white digits over a gray drop shadow on a
    cream background. The white layer is on top, so it is never occluded.
    Cream is (245, 245, 220): its blue channel is clearly lower than red.
    """

    image = image.convert("RGB")
    mask = Image.new("L", image.size, 255)
    mask.putdata([
        0 if (blue >= 238 and red - blue <= 8) else 255
        for red, _, blue in image.getdata()
    ])

    # Drop the 1-2 px frame drawn around the image.
    width, height = mask.size
    mask = mask.crop((3, 3, width - 3, height - 3))
    mask = ImageOps.expand(mask, border=12, fill=255)

    return mask.resize(
        (mask.width * 3, mask.height * 3),
        Image.LANCZOS,
    ).convert("RGB")


def _recognize(image):

    import torch

    processor, model = _load_model()
    pixel_values = processor(images=image, return_tensors="pt").pixel_values

    with torch.no_grad():
        generated_ids = model.generate(pixel_values, max_new_tokens=10)

    return processor.batch_decode(generated_ids, skip_special_tokens=True)[0]


def solve_captcha(image_bytes):
    """Return the 4-digit CAPTCHA text, or None if it could not be read."""

    image = Image.open(io.BytesIO(image_bytes))

    for candidate in (preprocess(image), image.convert("RGB")):
        text = _recognize(candidate)
        digits = re.sub(r"\D", "", text.replace("O", "0").replace("o", "0"))

        if len(digits) == CAPTCHA_LENGTH:
            return digits

    return None


if __name__ == "__main__":
    import sys

    for path in sys.argv[1:]:
        with open(path, "rb") as file:
            print(path, "->", solve_captcha(file.read()))
