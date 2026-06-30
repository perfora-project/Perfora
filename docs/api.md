# Python API

The command line is a thin shell over this library. Everything below is
generated from the source docstrings.

## Top-level

```{eval-rst}
.. automodule:: perfora
   :members: process, read, write
```

## Stepwise execution (Session)

```{eval-rst}
.. autoclass:: perfora.pipeline.session.Session
   :members:

.. autoclass:: perfora.pipeline.session.StageResult

.. autoclass:: perfora.pipeline.overrides.Overrides

.. autoclass:: perfora.pipeline.overrides.NoteEdit

.. autoclass:: perfora.pipeline.overrides.TextEdit
```

## Sources

```{eval-rst}
.. autoclass:: perfora.sources.image_source.ImageSource
   :members:

.. autoclass:: perfora.sources.video_source.VideoSource
   :members:

.. autoclass:: perfora.sources.base.RollImage
```

## Data model

```{eval-rst}
.. automodule:: perfora.model.document
   :members:

.. automodule:: perfora.model.geometry
   :members:

.. autoclass:: perfora.model.calibration.Calibration
   :members:
```

## I/O and the format registry

```{eval-rst}
.. autofunction:: perfora.io.registry.read_document
.. autofunction:: perfora.io.registry.write_document
.. autofunction:: perfora.io.registry.available_formats
.. autofunction:: perfora.io.registry.register_reader
.. autofunction:: perfora.io.registry.register_writer

.. autoclass:: perfora.io.base.Reader
   :members:

.. autoclass:: perfora.io.base.Writer
   :members:
```

## Text backends

```{eval-rst}
.. automodule:: perfora.text.base
   :members:
```

## Errors

```{eval-rst}
.. automodule:: perfora.errors
   :members:
```
