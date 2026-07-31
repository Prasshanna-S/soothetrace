# Contributing to SootheTrace

Thanks for helping improve a careful, evidence-limited prototype.

## Before you start

1. Read the [README](README.md), [technical architecture](docs/TECHNICAL-ARCHITECTURE.md), [evaluation note](docs/EVALUATION.md), and [privacy guidance](PRIVACY.md).
2. Create a branch from the current default branch.
3. Install Python 3.12 dependencies and FFmpeg.
4. Run the relevant tests before and after your change.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Contribution expectations

- Keep infant-cry presence, profile matching, and care-memory ranking conceptually separate.
- Preserve abstention paths. Do not turn similarity values into probabilities or forced names.
- Do not add causal cry labels, diagnostic claims, or medical advice.
- Do not commit personal audio, voice data, family history, keys, certificates, databases, downloaded models, or generated runtime artifacts.
- Add or update tests for behavioral changes.
- Document any new model, fixture, dataset, or visual asset in `THIRD_PARTY.md` before it is merged.
- Keep optional cloud processing opt-in and clearly disclosed.

## Pull requests

Explain the problem, the design choice, validation performed, and privacy or safety implications. Call out changes that affect stored data, model downloads, audio handling, API shape, evaluation claims, or dependency licences.

Do not present a small local test as population accuracy. If a result depends on a private or consented fixture pack, make the test optional and describe its limitation without publishing the fixture.

## Code of conduct

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
