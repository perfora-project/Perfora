"""Tesseract OCR recognizer backend (requires the ``[tesseract]`` extra).

The ``pytesseract`` import happens inside :meth:`TesseractRecognizer.__init__`
so that merely importing this module does not pull in the dependency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from perfora.errors import MissingBackendError
from perfora.model.document import TextKind
from perfora.text.base import RecognitionResult

if TYPE_CHECKING:
    from numpy.typing import NDArray


class TesseractRecognizer:
    """Recognize printed text in a cropped image region using Tesseract.

    Parameters
    ----------
    lang : str, optional
        Tesseract language string (e.g. ``"eng"``).  Defaults to ``"eng"``.

    Raises
    ------
    perfora.errors.MissingBackendError
        If ``pytesseract`` is not installed.
    """

    id = "tesseract"
    handles: TextKind = TextKind.PRINTED

    def __init__(self, lang: str = "eng") -> None:
        try:
            import pytesseract
        except ImportError as exc:
            raise MissingBackendError("tesseract", "tesseract") from exc

        self._pytesseract: Any = pytesseract
        self._lang = lang

    def recognize(self, crop: NDArray[Any]) -> RecognitionResult:
        """Run Tesseract on *crop* and return text with averaged confidence.

        Parameters
        ----------
        crop : NDArray
            A ``uint8`` numpy array (greyscale or BGR) of the detected text
            region.

        Returns
        -------
        RecognitionResult
            ``text`` is the joined word-level output; ``confidence`` is the
            mean word confidence mapped from the 0-100 Tesseract scale to
            ``[0, 1]``.  Empty results return ``("", 0.0)``.
        """
        output_type = self._pytesseract.Output.DICT
        data: dict[str, list[Any]] = self._pytesseract.image_to_data(
            crop,
            lang=self._lang,
            output_type=output_type,
        )

        confs: list[float] = []
        words: list[str] = []
        for word, conf in zip(data["text"], data["conf"], strict=True):
            # conf is -1 for non-word rows; skip those and blank words
            try:
                conf_float = float(conf)
            except (ValueError, TypeError):
                continue
            if conf_float < 0:
                continue
            word_str = str(word).strip()
            if not word_str:
                continue
            words.append(word_str)
            confs.append(conf_float)

        if not words:
            return RecognitionResult(text="", confidence=0.0)

        text = " ".join(words)
        confidence = (sum(confs) / len(confs)) / 100.0
        return RecognitionResult(text=text, confidence=confidence)
