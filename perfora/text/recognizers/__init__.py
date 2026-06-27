"""Text recognizer backends for perfora.

No backend is imported at package-load time.  Each backend imports its heavy
dependency lazily (inside ``__init__`` or first use) and raises
:class:`~perfora.errors.MissingBackendError` if the required extra is absent.

Import backends explicitly when needed:

.. code-block:: python

    from perfora.text.recognizers.tesseract import TesseractRecognizer
    from perfora.text.recognizers.trocr import TrocrRecognizer
"""

from __future__ import annotations
