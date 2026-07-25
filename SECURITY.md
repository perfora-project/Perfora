# Security policy

## Supported versions

perfora is pre-1.0 and under active development. Only the latest release on
`main` receives fixes.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

- Preferred: use GitHub's private reporting —
  [report a vulnerability](https://github.com/perfora-project/Perfora/security/advisories/new).
- Alternatively, email **alexander.vollmer.95@hotmail.de** with "perfora
  security" in the subject.

Please include what you did, what happened, and the input that triggered it
(a minimal file is ideal). You can expect an acknowledgement within a week.

## What is in scope

perfora reads untrusted image and video files, and parses documents written by
other tools. Realistic concerns are therefore:

- a crafted image, video or `.perfora.json` file causing memory exhaustion,
  unbounded allocation or arbitrary file writes;
- path traversal via a document's recorded provenance or an output path;
- code execution through a deserialization path.

Note that heavy image decoding happens inside OpenCV, scikit-image and the OCR
backends. Vulnerabilities in those belong upstream, but please still tell us so
the dependency can be pinned or worked around.

## What is out of scope

- The bundled quickstart notebook and `perfora-notebook` run a Jupyter server.
  Binding it to a non-loopback address (`--ip 0.0.0.0`, as the Docker image
  does) exposes a code-execution surface **by design** — that is what a notebook
  is. Only do it on a network you trust.
- Anything requiring a user to run a command they wrote themselves against their
  own files.
- Optional OCR backends downloading models on first use (documented behaviour;
  no network access happens at import time).
