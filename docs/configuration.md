# Configuration reference

Every tunable threshold lives in a single frozen
{py:class}`perfora.config.Config` dataclass. Override any field from the command
line with a JSON file (`--config cfg.json`) or from Python
(`perfora.process(..., config=Config(...))`). You only set the fields you want to
change; the rest keep their defaults.

```bash
echo '{"bridge_gap_mm": 0.0, "binarization_mode": "bright_holes"}' > cfg.json
uv run perfora -i roll.tif -o roll.perfora.json --dpi 600 --config cfg.json
```

The complete list of fields, with their defaults and meanings, is generated
directly from the source below — so it is always current.

```{eval-rst}
.. autoclass:: perfora.config.Config
   :members:
   :member-order: bysource
```
