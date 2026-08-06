# Deploy runbook — the engine on the practice's box

Written for an **agent session** driving the box over a shell, with no prior
context beyond this file. Follow it top to bottom; nothing here should require
asking the owner a question mid-deploy. If a step's output doesn't match what's
shown, stop and surface the mismatch rather than improvising past it.

Covers deploying the **engine** — the MCP server and the substrate it serves —
onto a box that already runs `systemd`, has `uv` on `PATH`, and already runs
LiteLLM registered against it (map [#45](https://github.com/javier-abia/urbandocs/issues/45),
[#43](https://github.com/javier-abia/urbandocs/issues/43)). Provisioning the box
itself, installing LiteLLM, and wiring Langsmith are **not** covered here — see
map #45's Out of scope.

No containers, no CD. One box, one practice, an infrequent deploy: a correct
runbook beats a pipeline nobody trusts (map #45). Pull-based automation is
deferred fog, not a step below.

## Layout on the box

```
/opt/urbandocs/            <- the checkout; assumed path, see "Judgment calls"
├── corpus/                <- gitignored, rebuilt on the box, never shipped
├── documentos/             <- committed docling-tuned/*.json travel with the checkout
├── src/urbandocs/
└── pyproject.toml / uv.lock
```

`urbandocs.paths` resolves the repo root by upward search for `pyproject.toml`,
so nothing needs a hardcoded path *inside* the code — but the `systemd` unit
below pins `$URBANDOCS_ROOT` explicitly anyway, so the service's behaviour
doesn't depend on `WorkingDirectory` staying in sync with it by accident.

## First-time setup (once per box)

1. Create a dedicated system user the service runs as — no login shell, no
   sudo:
   ```sh
   sudo useradd --system --create-home --home-dir /opt/urbandocs --shell /usr/sbin/nologin urbandocs
   ```
2. Clone the repo into that home directory as that user:
   ```sh
   sudo -u urbandocs git clone <remote-url> /opt/urbandocs
   ```
3. Install the `systemd` unit — see [The systemd unit](#the-systemd-unit) below
   — to `/etc/systemd/system/urbandocs.service`, then:
   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable urbandocs.service
   ```
4. Continue with **Deploy steps** below to do the first real start.

## Deploy steps (every deploy)

Run as the `urbandocs` user, from the checkout:

```sh
cd /opt/urbandocs
sudo -u urbandocs git fetch origin
sudo -u urbandocs git checkout <ref>          # a tag or commit; see Rollback
sudo -u urbandocs uv sync --frozen --no-dev   # runtime deps only — mcp SDK's
                                               # 31-package tree, not ruff/ty/pytest
sudo -u urbandocs uv run --frozen python -m urbandocs.ingest
sudo -u urbandocs uv run --frozen python -m urbandocs.check_corpus
sudo systemctl restart urbandocs.service
```

`ingest` rebuilds `corpus/corpus.tsv` from the committed `docling-tuned/*.json`
— 0.7s, stdlib only, no ML toolchain (#28). `corpus/` is gitignored and derived,
so it is **never** shipped; every deploy rebuilds it on the box. `check_corpus`
is the acceptance gate CI also runs — a rebuild that fails it should not be
restarted into. If it fails, stop and diagnose before touching the service.

**`--no-dev` matters.** `uv sync` alone installs the `dev` group too — ruff,
ty, pytest, pre-commit — none of which the running service needs and all of
which drag their own resolution weight onto the box. `--frozen` on every `uv`
invocation means the box only ever installs what `uv.lock` says; it never
re-resolves, so a `uv.lock` conflict fails loudly here rather than silently
drifting the box's tree from what CI tested.

## The `systemd` unit

Fixed by [#43](https://github.com/javier-abia/urbandocs/issues/43): loopback
bind (`127.0.0.1:8848`), streamable HTTP, no auth on the engine (LiteLLM is
the only caller, on the same host). Nothing here opens a firewall rule,
because nothing needs one.

```ini
# /etc/systemd/system/urbandocs.service
[Unit]
Description=urbandocs normativa-search MCP server
After=network.target

[Service]
Type=simple
User=urbandocs
Group=urbandocs
WorkingDirectory=/opt/urbandocs
Environment=URBANDOCS_ROOT=/opt/urbandocs
ExecStart=/usr/bin/env uv run --frozen python -m urbandocs.server
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=urbandocs

# No network exposure to lock down beyond the bind itself (127.0.0.1:8848,
# set in the server's own startup, #43) -- there is no LAN-facing socket for
# systemd sandboxing to help with. ProtectSystem/PrivateTmp are omitted rather
# than cargo-culted: they'd protect against a compromise of a process that
# already has no network reach and no secrets of its own.

[Install]
WantedBy=multi-user.target
```

`python -m urbandocs.server` matches the existing invocation convention
(`python -m urbandocs.ingest`, `python -m urbandocs.check_corpus`) and is
this runbook's naming choice for the entry point — see
[Judgment calls](#judgment-calls-made-here) below.

`corpus/` and `documentos/` are located the same way the gates locate them:
`$URBANDOCS_ROOT` first, so the unit's `Environment=` line is what the server
reads, independent of `WorkingDirectory`.

## Corpus-only change (adding or re-converting a document)

Two different deploys, not one:

- **A code or config change** (the common case): the steps above. `ingest`
  rebuilds from docling-tuned JSON already committed to the checkout — no ML
  toolchain touches the box.
- **A new or re-converted document**: Stage 1 has to run first, on the box,
  because its output — `documentos/documentos-docling/docling-tuned/<doc>.json`
  — is what gets *committed*, and committing it is what keeps Stage 2 an
  ML-toolchain-free 0.7s rebuild for every deploy after. This is the ~20-minute
  path (map #45), and it is **not** part of the routine deploy above:

  ```sh
  cd /opt/urbandocs/tools/docling-convert
  sudo -u urbandocs uv run main.py --dst ../../documentos/documentos-docling/docling-tuned
  ```

  `tools/docling-convert` resolves its own toolchain (its own `pyproject.toml`
  and `uv.lock`, docling + EasyOCR) independently of the root project's `uv
  sync` — see its README for `--ocr`/`--no-ocr`/`--force` and why
  `--full-page-ocr` is never passed.

  Then, from a machine with push access (not necessarily the box):
  ```sh
  git add documentos/documentos-docling/docling-tuned/<doc>.json
  git commit -m "feat: add <doc> to the corpus"
  git push
  ```
  and only then does the box `git checkout` the new commit and run the
  **Deploy steps** above — `ingest` picks up the new JSON on the next 0.7s
  rebuild. Stage 1 output is a committed input, not a deploy artifact; it has
  to land on `main` before it can be deployed anywhere.

## Rollback

```sh
cd /opt/urbandocs
sudo -u urbandocs git checkout <previous-ref>
sudo -u urbandocs uv sync --frozen --no-dev
sudo -u urbandocs uv run --frozen python -m urbandocs.ingest
sudo -u urbandocs uv run --frozen python -m urbandocs.check_corpus
sudo systemctl restart urbandocs.service
```

Same shape as a forward deploy — `git checkout` plus rebuild plus restart —
because `corpus/corpus.tsv` is derived, never carried across the rollback by
hand. **When the rollback crosses a corpus-format change** (a `Row`/`COLUMNS`
change in `ingest.py`, or a `docling-tuned/*.json` shape change): the checked-
out `<previous-ref>`'s own `ingest.py` runs against its own committed
`docling-tuned/*.json`, present at that commit — the pair moves together, so
`ingest` and its inputs are never mismatched mid-rollback. `check_corpus`
after the rebuild is what catches a rollback that silently produced a corpus
the older code didn't expect; treat a failure there as a rollback that isn't
finished, not as a rollback that succeeded with warnings.

`<previous-ref>` names no version by itself — this repo currently has no tags
or version file, so "previous" means whatever commit the last known-good
deploy checked out, tracked by whoever runs the deploy. Tagging deploys is
open fog on map #45, not decided here.

## Verification after deploy

Two checks — local liveness, then the thing that actually matters end to end.

**1. The server is up and speaking MCP**, straight to the loopback bind,
bypassing LiteLLM:

```sh
curl -s http://127.0.0.1:8848/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"deploy-check","version":"0"}}}'
```

A healthy answer is a `200` with a JSON-RPC `result` carrying `serverInfo` and
a non-empty `capabilities.tools`. A connection refused means the unit didn't
start — `journalctl -u urbandocs.service` next. A `4xx`/`5xx` with a JSON-RPC
error means it started but rejected the handshake — check `allowed_hosts` and
the `MCP-Protocol-Version` header first, since DNS-rebinding protection is the
engine's only access control (#43) and rejects on those two axes before
anything else.

**2. Tool descriptions survive LiteLLM's aggregation, through the real path
an architect uses.** This is the check that matters more than #1: the term
floor in `search`'s tool description is *instructed*, not structural
([#42](https://github.com/javier-abia/urbandocs/issues/42),
[#28](https://github.com/javier-abia/urbandocs/issues/28)'s `\b`/`\y` finding
is this engine's worst-failure shape), so a gateway that truncates or
rewrites it on the way through would silently weaken every sweep without
tripping check #1 at all.

```sh
curl -s <litellm-url>/normativa/mcp \
  -H "Authorization: Bearer $LITELLM_API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

A healthy answer lists `search`, `get`, `get_by_cite`, `get_page`, and
`search`'s `description` field, byte-for-byte, states the term floor — every
content word searched on its own, entity and attribute separately. Diff it
against the description in the server source
(`urbandocs.server`/wherever #59 lands it) rather than eyeballing it; a
truncation can be a handful of characters short and still read as prose.

## Where this runbook lives, and who it's for

`docs/ops/deploy-runbook.md` — new directory, parallel to `docs/agents/` (docs
written for an agent session to act on, as opposed to `docs/research/`, which
is evidence for decisions already made). This file is that: an agent session
should be able to execute every command above without asking, given shell
access to the box.

## Judgment calls made here

Recorded rather than silently assumed, because none of them were asked for
directly and a later ticket may need to revisit one:

- **`/opt/urbandocs` as the checkout path** and a dedicated `urbandocs` system
  user — a convention, not a constraint from any prior ticket. Change both in
  one pass through this file if the box's actual provisioning (out of this
  ticket's scope) picks something else.
- **`python -m urbandocs.server` as the entry point module name.** Matches
  the existing `python -m urbandocs.<name>` convention
  (`ingest`, `check_corpus`), but no ticket has named it yet —
  [#59](https://github.com/javier-abia/urbandocs/issues/59) ("Stand up the MCP
  server and expose search over the wire") is what will actually create the
  module, and this runbook is written normatively: #59 should land the module
  at this name, or this file needs a one-line update if it lands elsewhere.
- **`uv sync --frozen --no-dev` for the runtime tree.** `--no-dev` excludes
  the dev dependency group (ruff/ty/pytest/pre-commit); nothing in this repo's
  config splits a narrower "runtime" group out, so this is the whole
  toolchain minus dev, not a curated runtime set. If the dependency groups are
  ever restructured, revisit this flag.
- **No TLS, no firewall rule, no LAN bind anywhere in this file** — inherited
  directly from #43, not re-decided here.
