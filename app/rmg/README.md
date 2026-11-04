# Resource Management (RMG)

A second assistant inside the same application. In the web app, the **HR | RMG** toggle in the header chooses
which assistant answers. Everything specific to resource management lives in this folder.

## How it is wired

- The web app sends `mode: "rmg"` with each chat message (`POST /chat`). Without it the message goes to the HR agent.
- `app/api/main.py` picks the agent by mode, keeps the two conversations apart (thread ids carry the mode), and
  never lets a bare "yes" or "no" in RMG mode confirm an HR draft.
- `GET /features` tells the web app whether to show the toggle. `RMG_ENABLED=false` removes RMG from a deployment.
- `app/server.py` builds both agents on one checkpoint saver.

## Files

- `agent.py`   the graph: guardrail, tool loop, verify, rewrite, fallback. It keeps the HR agent's state names, so
               `stream_turn` and the web app work unchanged.
- `prompts.py` the system prompt (versioned with `PROMPT_VERSION`).
- `tools.py`   the tool allowlist (`RMG_TOOL_NAMES`) and the call wrapper. Read-only.
- `factory.py` builds the live agent with the answer model.

It reuses: the input guardrail, the answer verifier, the deterministic fallback, the tool registry, the audit log
and the model settings. The HR agent imports nothing from this folder.

## What it can do today

Read-only questions from existing data: which of a manager's direct reports are on leave (managers only), company
holidays, and working-day counts. Projects, allocations and skills are not connected yet.

## Adding a capability

1. Write the tests first (`tests/unit/test_rmg_agent.py` shows the pattern with a scripted model).
2. For a read-only tool that already exists, add its name to `RMG_TOOL_NAMES`.
3. For a new tool, define it with the `@tool` decorator in a module in this folder and add its name to
   `RMG_TOOL_NAMES`. Two core changes are needed the first time: `_load_tools` in `app/tools/registry.py` must load
   the new module, and the registry needs a domain tag so the HR agent cannot see RMG tools.
4. Writes follow draft-and-confirm like `prepare_leave_request`; do not let the model write directly.
5. If the prompt changes, bump `PROMPT_VERSION`.
