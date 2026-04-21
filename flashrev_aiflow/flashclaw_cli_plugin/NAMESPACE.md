# `flashclaw_cli_plugin/` is a PEP 420 namespace package

> **Do NOT add an `__init__.py` to this directory.**
> **Do NOT flatten this layout.**

## What this directory is

This directory has **no `__init__.py` on purpose**. It is a
[PEP 420 implicit namespace package](https://peps.python.org/pep-0420/).
Its sole job is to let multiple **independent PyPI packages** be imported
under the same top-level name `flashclaw_cli_plugin.*`.

This module (`flashrev_aiflow/`) ships as the PyPI package
`flashclaw-cli-plugin-flashrev-aiflow`; sibling modules (e.g. `call_svc/`)
ship as their own PyPI packages. When both are installed in the same
Python environment, the interpreter stitches their
`flashclaw_cli_plugin/` directories together so you can write:

```python
from flashclaw_cli_plugin.flashrev_aiflow.core.client import FlashrevAiflowClient
from flashclaw_cli_plugin.call_svc.core.client        import CallSvcClient
```

## Why the seemingly-duplicated naming

The path looks like `flashrev_aiflow/flashclaw_cli_plugin/flashrev_aiflow/...`. The two
`flashrev_aiflow` segments and the two `flashclaw_cli_plugin` references
(outer git repo folder + this namespace) are **different layers**:

| Layer | Role | Named for |
|---|---|---|
| `<repo-root>/` | Git repository directory | The family of plugins |
| `flashrev_aiflow/` | PyPI distribution source root (`pyproject.toml` lives here) | The PyPI package tail (`flashclaw-cli-plugin-**flashrev-aiflow**`) |
| `flashrev_aiflow/flashclaw_cli_plugin/` | **this directory** - PEP 420 namespace | The PyPI package head (`**flashclaw-cli-plugin**-flashrev-aiflow`) |
| `flashrev_aiflow/flashclaw_cli_plugin/flashrev_aiflow/` | Regular Python package with `__init__.py` | The Python import path end |

## Why not flatten to `flashrev_aiflow/flashrev_aiflow/...`

Flattening would:
1. Break every `from flashclaw_cli_plugin.flashrev_aiflow...` import in
   downstream code and in ClawHub-delivered agent scripts.
2. Expose `flashrev_aiflow` as a top-level name on PyPI, losing the
   namespace-based squatting protection that `flashclaw-cli-plugin-*`
   provides.
3. Defeat the plugin-discovery pattern
   (`pkgutil.iter_modules(flashclaw_cli_plugin.__path__)`).
4. Require a separate top-level import name for every new sibling module
   (email-svc, crm-svc, ...) - each of which would have to avoid
   collisions with unrelated PyPI packages.

## Prior art

This is the same pattern used by Google Cloud SDK
(`google.cloud.storage`, `google.cloud.bigtable`), Zope (`zope.interface`,
`zope.event`), Sphinx extensions (`sphinxcontrib.plantuml`,
`sphinxcontrib.mermaid`), and Python's `backports.*` family.
