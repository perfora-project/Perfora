"""TrOCR handwriting recognizer backend (requires the ``[trocr]`` extra).

The ``transformers``, ``torch``, and ``PIL`` imports are deferred to first use
so that importing this module does not trigger any heavy ML dependency load.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from perfora.errors import MissingBackendError
from perfora.model.document import TextKind
from perfora.text.base import RecognitionResult

if TYPE_CHECKING:
    from numpy.typing import NDArray

# Fixed confidence returned by TrOCR: the model's ``generate`` output does not
# expose a clean token-level probability that maps cleanly to [0,1], so we
# return a moderate fixed value and document it clearly.
_TROCR_CONFIDENCE = 0.5


class TrocrRecognizer:
    """Recognize handwritten text using Microsoft's TrOCR model.

    The Hugging Face model is downloaded on first use and cached by the
    ``transformers`` library.  No network call happens at construction time.

    Parameters
    ----------
    model_name : str, optional
        The Hugging Face model identifier.
        Defaults to ``"microsoft/trocr-base-handwritten"``.

    Raises
    ------
    perfora.errors.MissingBackendError
        Raised on first :meth:`recognize` call if ``transformers``,
        ``torch``, or ``pillow`` are not installed.

    Notes
    -----
    **Confidence** — TrOCR's ``generate`` call does not expose a clean
    sequence-level confidence that maps into ``[0, 1]`` without significant
    overhead (e.g. beam-search log-probs).  The returned
    :attr:`~perfora.text.base.RecognitionResult.confidence` is therefore a
    fixed moderate value of ``0.5``.  Downstream callers should treat TrOCR
    output as uncertain and let the review queue arbitrate.
    """

    id = "trocr"
    handles: TextKind = TextKind.HANDWRITTEN

    def __init__(self, model_name: str = "microsoft/trocr-base-handwritten") -> None:
        self._model_name = model_name
        # Processor and model are lazily loaded on first recognize call.
        self._processor: Any = None
        self._model: Any = None

    def _ensure_loaded(self) -> None:
        """Load processor and model on first use."""
        if self._processor is not None:
            return
        try:
            import torch  # noqa: F401
            from PIL import Image as _PILImage  # noqa: F401
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        except ImportError as exc:
            raise MissingBackendError("trocr", "trocr") from exc

        self._processor = TrOCRProcessor.from_pretrained(self._model_name)
        self._model = VisionEncoderDecoderModel.from_pretrained(self._model_name)

    def recognize(self, crop: NDArray[Any]) -> RecognitionResult:
        """Run TrOCR on *crop* and return the transcribed text.

        Parameters
        ----------
        crop : NDArray
            A ``uint8`` numpy array (greyscale or BGR) containing the
            handwritten text region.

        Returns
        -------
        RecognitionResult
            ``confidence`` is always ``0.5`` (see class-level note).

        Raises
        ------
        perfora.errors.MissingBackendError
            If ``transformers``, ``torch``, or ``pillow`` are not installed.
        """
        self._ensure_loaded()

        # Deferred import: PIL is only needed here; it's bundled with the
        # [trocr] extra so it's guaranteed to be present after _ensure_loaded.
        import torch
        from PIL import Image

        # Convert numpy array to PIL RGB image (TrOCR expects RGB).
        if crop.ndim == 2:
            pil_img = Image.fromarray(crop).convert("RGB")
        else:
            import cv2  # already a core dep

            rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)

        pixel_values = self._processor(images=pil_img, return_tensors="pt").pixel_values
        with torch.no_grad():
            generated_ids = self._model.generate(pixel_values)
        text: str = self._processor.batch_decode(
            generated_ids, skip_special_tokens=True
        )[0]

        return RecognitionResult(text=text, confidence=_TROCR_CONFIDENCE)
