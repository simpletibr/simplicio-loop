INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:torchtitan','project_skill','skill://simplicio-runtime/torchtitan','skill: torchtitan','---
name: distributed-llm-pretraining-torchtitan
description: Provides PyTorch-native distributed LLM pretraining using torchtitan with 4D parallelism (FSDP2, TP, PP, CP). Use when pretraining Llama 3.1, DeepSeek V3, or custom models at scale from 8 to 512+ GPUs with Float8, torch.compile, and distributed checkpointing.
version: 1.0.0
author: Orchestra Research
license: MIT
dependencies: [torch>=2.6.0, torchtitan>=0.2.0, torchao>=0.5.0]
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Model Architecture, Distributed Training, TorchTitan, FSDP2, Tensor Parallel, Pipeline Parallel, Context Parallel, Float8, Llama, Pretraining]

---

# TorchTitan - PyTorch Native Distributed LLM Pretraining

## Quick start

TorchTitan is PyTorch''s official platform for large-scale LLM pretraining with composable 4D parallelism (FSDP2, TP, PP, CP), achieving 65%+ speedups over baselines on H100 GPUs.

**Installation**:
```bash
# From PyPI (stable)
pip install torchtitan

# From source (latest features, requires PyTorch nightly)
git clone https://github.com/pytorch/torchtitan
cd torchtitan
pip install -r requirements.txt
```

**Download tokenizer**:
```bash
# Get HF token from https://huggingface.co/settings/tokens
python scripts/download_hf_assets.py --repo_id meta-llama/Llama-3.1-8B --assets tokenizer --hf_token=...
```

**Start training on 8 GPUs**:
```bash
CONFIG_FILE="./torchtitan/models/llama3/train_configs/llama3_8b.toml" ./run_train.sh
```

## Common workflows

### Workflow 1: Pretrain Llama 3.1 8B on single node

Copy this checklist:

```
Single Node Pretraining:
- [ ] Step 1: Download tokenizer
- [ ] Step 2: Configure training
- [ ] Step 3: Launch training
- [ ] Step 4: Monitor and checkpoint
```

**Step 1: Download tokenizer**

```bash
python scripts/download_hf_assets.py \
  --repo_id meta-llama/Llama-3.1-8B \
  --assets tokenizer \
  --hf_token=YOUR_HF_TOKEN
```

**Step 2: Configure training**

Edit or create a TOML config file:

```toml
# llama3_8b_custom.toml
[job]
dump_folder = "./outputs"
description = "Llama 3.1 8B training"

[model]
name = "llama3"
flavor = "8B"
hf_assets_path = "./assets/hf/Llama-3.1-8B"

[optimizer]
name = "AdamW"
lr = 3e-4

[lr_scheduler]
warmup_steps = 200

[training]
local_batch_size = 2
seq_len = 8192
max_norm = 1.0
steps = 1000
dataset = "c4"

[parallelism]
data_parallel_shard_degree = -1  # Use all GPUs for FSDP

[activation_checkpoint]
mode = "selective"
selective_ac_option = "op"

[checkpoint]
enable = true
folder = "checkpoint"
interval = 500
```

**Step 3: Launch training**

```bash
# 8 GPUs on single node
CONFIG_FILE="./llama3_8b_custom.toml" ./run_train.sh

# Or explicitly with torchrun
torchrun --nproc_per_node=8 \
  -m torchtitan.train \
  --job.config_file ./llama3_8b_custom.toml
```

**Step 4: Monitor and checkpoint**

TensorBoard logs are saved to `./outputs/tb/`:
```bash
tensorboard --logdir ./outputs/tb
```

### Workflow 2: Multi-node training with SLURM

```
Multi-Node Training:
- [ ] Step 1: Configure parallelism for scale
- [ ] Step 2: Set up SLURM script
- [ ] Step 3: Submit job
- [ ] Step 4: Resume from checkpoint
```

**Step 1: Configure parallelism for scale**

For 70B model on 256 GPUs (32 nodes):
```toml
[parallelism]
data_parallel_shard_degree = 32  # FSDP across 32 ranks
tensor_parallel_degree = 8        # TP within node
pipeline_parallel_degree = 1      # No PP for 70B
context_parallel_degree = 1       # Increase for long sequences
```

**Step 2: Set up SLURM script**

```bash
#!/bin/bash
#SBATCH --job-name=llama70b
#SBATCH --nodes=32
#SBATCH --ntasks-per-node=8
#SBATCH --gpus-per-node=8

srun torchrun \
  --nnodes=32 \
  --nproc_per_node=8 \
  --rdzv_backend=c10d \
  --rdzv_endpoint=$MASTER_ADDR:$MASTER_PORT \
  -m torchtitan.train \
  --job.config_file ./llama3_70b.toml
```

**Step 3: Submit job**

```bash
sbatch multinode_trainer.slurm
```

**Step 4: Resume from checkpoint**

Training auto-resumes if checkpoint exists in configured folder.

### Workflow 3: Enable Float8 training for H100s

Float8 provides 30-50% speedup on H100 GPUs.

```
Float8 Training:
- [ ] St','.simplicio-loop\skills\torchtitan\SKILL.md','cdbf5e89459dd0a08c8ab6ec2e49764c071927edc8a88a20a12737edd68f2baf','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:touchdesigner-mcp','project_skill','skill://simplicio-runtime/touchdesigner-mcp','skill: touchdesigner-mcp','---
name: touchdesigner-mcp
description: "Control a running TouchDesigner instance via twozero MCP — create operators, set parameters, wire connections, execute Python, build real-time visuals. 36 native tools."
version: 1.1.0
author: kshitijk4poor
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [TouchDesigner, MCP, twozero, creative-coding, real-time-visuals, generative-art, audio-reactive, VJ, installation, GLSL]
    related_skills: [native-mcp, ascii-video, manim-video, hermes-video]

---

# TouchDesigner Integration (twozero MCP)

## CRITICAL RULES

1. **NEVER guess parameter names.** Call `td_get_par_info` for the op type FIRST. Your training data is wrong for TD 2025.32.
2. **If `tdAttributeError` fires, STOP.** Call `td_get_operator_info` on the failing node before continuing.
3. **NEVER hardcode absolute paths** in script callbacks. Use `me.parent()` / `scriptOp.parent()`.
4. **Prefer native MCP tools over td_execute_python.** Use `td_create_operator`, `td_set_operator_pars`, `td_get_errors` etc. Only fall back to `td_execute_python` for complex multi-step logic.
5. **Call `td_get_hints` before building.** It returns patterns specific to the op type you''re working with.

## Architecture

```
Hermes Agent -> MCP (Streamable HTTP) -> twozero.tox (port 40404) -> TD Python
```

36 native tools. Free plugin (no payment/license — confirmed April 2026).
Context-aware (knows selected OP, current network).
Hub health check: `GET http://localhost:40404/mcp` returns JSON with instance PID, project name, TD version.

## Setup (Automated)

Run the setup script to handle everything:

```bash
bash "${HERMES_HOME:-$HOME/.hermes}/skills/creative/touchdesigner-mcp/scripts/setup.sh"
```

The script will:
1. Check if TD is running
2. Download twozero.tox if not already cached
3. Add `twozero_td` MCP server to Hermes config (if missing)
4. Test the MCP connection on port 40404
5. Report what manual steps remain (drag .tox into TD, enable MCP toggle)

### Manual steps (one-time, cannot be automated)

1. **Drag `~/Downloads/twozero.tox` into the TD network editor** → click Install
2. **Enable MCP:** click twozero icon → Settings → mcp → "auto start MCP" → Yes
3. **Restart Hermes session** to pick up the new MCP server

After setup, verify:
```bash
nc -z 127.0.0.1 40404 && echo "twozero MCP: READY"
```

## Environment Notes

- **Non-Commercial TD** caps resolution at 1280×1280. Use `outputresolution = ''custom''` and set width/height explicitly.
- **Codecs:** `prores` (preferred on macOS) or `mjpa` as fallback. H.264/H.265/AV1 require a Commercial license.
- Always call `td_get_par_info` before setting params — names vary by TD version (see CRITICAL RULES #1).

## Workflow

### Step 0: Discover (before building anything)

```
Call td_get_par_info with op_type for each type you plan to use.
Call td_get_hints with the topic you''re building (e.g. "glsl", "audio reactive", "feedback").
Call td_get_focus to see where the user is and what''s selected.
Call td_get_network to see what already exists.
```

No temp nodes, no cleanup. This replaces the old discovery dance entirely.

### Step 1: Clean + Build

**IMPORTANT: Split cleanup and creation into SEPARATE MCP calls.** Destroying and recreating same-named nodes in one `td_execute_python` script causes "Invalid OP object" errors. See pitfalls #11b.

Use `td_create_operator` for each node (handles viewport positioning automatically):

```
td_create_operator(type="noiseTOP", parent="/project1", name="bg", parameters={"resolutionw": 1280, "resolutionh": 720})
td_create_operator(type="levelTOP", parent="/project1", name="brightness")
td_create_operator(type="nullTOP", parent="/project1", name="out")
```

For bulk creation or wiring, use `td_execute_python`:

```python
# td_execute_python script:
root = op(''/project1'')
nodes = []
for name, optype in [(''bg'', noiseTOP), (''fx'', levelTOP), (''out'', nullTOP)]:
    n = root.create(optype, name)
    nodes.append(n.path)
# Wire chain
for i in range(len(nodes)-1):
    op(nodes[i]).outputConnectors[0].connect(op(nodes[i+1]).inputCo','.simplicio-loop\skills\touchdesigner-mcp\SKILL.md','1b933bd1121eba57cb0f699ec221ea489c02d6e4d76e18d53bbcc080fda02de3','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:typegpu','project_skill','skill://simplicio-runtime/typegpu','skill: typegpu','---
name: typegpu
description: TypeGPU and raw WebGPU adapter patterns for HyperFrames. Use when creating GPU-rendered compositions with TypeGPU, raw WebGPU, WGSL fragment shaders, compute pipelines, liquid glass effects, particle systems, or any canvas layer driven by navigator.gpu that responds to HyperFrames hf-seek events.
---

# TypeGPU / WebGPU for HyperFrames

HyperFrames supports TypeGPU and raw WebGPU through its `typegpu` runtime adapter. The adapter does not own your pipeline. It publishes HyperFrames time and dispatches a seek event so your composition can render the exact GPU frame.

## Contract

- Initialize WebGPU asynchronously (`await navigator.gpu.requestAdapter()`), but register all GSAP tweens **synchronously** — before any `await`. The HyperFrames player reads the timeline immediately at page load.
- Render from HyperFrames time, not `performance.now()`.
- Listen for the `hf-seek` event and re-render at exactly that time.
- Guard against environments where WebGPU is unavailable — the adapter does not check for you.
- For video renders, call `await device.queue.onSubmittedWorkDone()` after submitting GPU work to ensure the canvas is flushed before the frame is captured.

The adapter sets `window.__hfTypegpuTime` and dispatches `new CustomEvent("hf-seek", { detail: { time } })` on each seek.

## Basic Pattern

```html
<canvas id="gpu-layer"></canvas>
<script>
  (async () => {
    if (!navigator.gpu) return;
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) return;
    const device = await adapter.requestDevice();
    const canvas = document.getElementById("gpu-layer");
    canvas.width = 1920;
    canvas.height = 1080;
    const ctx = canvas.getContext("webgpu");
    const fmt = navigator.gpu.getPreferredCanvasFormat();
    ctx.configure({ device, format: fmt, alphaMode: "opaque" });

    // Build your pipeline, buffers, bind groups...
    const timeUniform = new Float32Array([0]);
    const timeBuf = device.createBuffer({
      size: 16,
      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
    });

    function render(t) {
      timeUniform[0] = t;
      device.queue.writeBuffer(timeBuf, 0, timeUniform);
      const enc = device.createCommandEncoder();
      const pass = enc.beginRenderPass({
        colorAttachments: [
          {
            view: ctx.getCurrentTexture().createView(),
            loadOp: "clear",
            clearValue: { r: 0, g: 0, b: 0, a: 1 },
            storeOp: "store",
          },
        ],
      });
      pass.setPipeline(pipeline);
      pass.setBindGroup(0, bindGroup);
      pass.draw(3);
      pass.end();
      device.queue.submit([enc.finish()]);
    }

    render(0);
    window.addEventListener("hf-seek", (e) => render(e.detail.time));
  })();
</script>
```

## Timeline Registration

GSAP tweens that drive text, captions, or HTML elements must be registered **synchronously** — before any `await`:

```js
const tl = gsap.timeline({ paused: true });

// Caption tweens: synchronous, added before WebGPU init
gsap.set(".cap", { opacity: 0 });
tl.to("#cap-1", { opacity: 1, duration: 0.3 }, 1.0);
tl.to("#cap-1", { opacity: 0, duration: 0.2 }, 3.5);

window.__timelines["my-comp"] = tl;

// GPU-dependent tweens can go inside the async IIFE
(async () => {
  // ... WebGPU init ...
  const proxy = { value: 0 };
  tl.to(proxy, { value: 1, duration: 2, onUpdate: render }, 0.5);
})();
```

## Video-Backed Effects (Liquid Glass, Distortion)

To use a `<video>` as the GPU input texture:

```js
const videoEl = document.getElementById("aroll");

// Wait for video metadata before creating the texture
await new Promise((r) => {
  if (videoEl.readyState >= 1) r();
  else videoEl.addEventListener("loadedmetadata", r, { once: true });
});

// Create texture at the video''s NATIVE resolution
const vw = videoEl.videoWidth,
  vh = videoEl.videoHeight;
const bgTex = device.createTexture({
  size: [vw, vh],
  format: "rgba8unorm",
  usage:
    GPUTextureUsage.COPY_DST | GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.RENDER_ATTACHMENT,
});

function render(t) ','.simplicio-loop\skills\typegpu\SKILL.md','c9f20195f0098dc0a2c5c6732aa176e93029d95e2492e31ff014223d20925c90','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:unreal-engine-mcp','project_skill','skill://simplicio-runtime/unreal-engine-mcp','skill: unreal-engine-mcp','---
name: unreal-engine-mcp
description: Drive Unreal Engine 5 editor over its local MCP server. Spawn actors, configure lighting and materials, run automation tests, execute editor scripting — all from Simplicio without leaving the terminal.
version: 1.0.0
requires: Unreal Engine 5.8+ with ModelContextProtocol plugin enabled
author: simplicio
tags: [unreal, ue5, 3d, lighting, materials, game-engine, mcp, editor-scripting]
platforms: [linux, macos, windows]
---

# Unreal Engine MCP

Drive a running Unreal Editor 5 instance from Simplicio via the official Epic
`ModelContextProtocol` plugin. The plugin embeds an HTTP+MCP server inside the
editor process and serves it on `http://127.0.0.1:8000/mcp` by default.

## Setup (one-time)

### 1. Enable the plugin inside Unreal Editor

    Edit > Plugins > search "Unreal MCP" → enable "ModelContextProtocol"

Restart the editor when prompted (the Toolset Registry dependency activates
automatically).

### 2. Start the MCP server

    Edit > Editor Preferences > General > Model Context Protocol
    → Enable "Auto Start Server"

Or run in the editor console:

    ModelContextProtocol.StartServer

The server binds to `http://127.0.0.1:8000/mcp` (port and path are
configurable in the same preferences pane).

### 3. Verify connection

    simplicio skill run unreal-engine-mcp ping

Expected output: `OK — Unreal MCP server is reachable at http://127.0.0.1:8000/mcp`

## Protocol

JSON-RPC 2.0 over HTTP POST. Every request:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "<tool_name>",
    "arguments": { "<key>": "<value>" }
  }
}
```

Response on success:
```json
{ "jsonrpc": "2.0", "id": 1, "result": { ... } }
```

Response on error:
```json
{ "jsonrpc": "2.0", "id": 1, "error": { "code": -32000, "message": "..." } }
```

## Available Commands (Simplicio CLI)

```
simplicio skill run unreal-engine-mcp [--url <URL>] [SUBCOMMAND]
```

| subcommand            | description                                      |
|-----------------------|--------------------------------------------------|
| (none / info)         | Show skill info and configured editor endpoint   |
| ping                  | TCP-probe the editor MCP server port             |
| call <tool> [JSON]    | Send a raw tool call to the editor               |
| lighting              | Print lighting tool usage examples               |
| material              | Print material tool usage examples               |

## Lighting Examples

### Check sky light intensity
```
simplicio skill run unreal-engine-mcp call set_actor_property \
  ''{"actor":"SkyLight","property":"Intensity","value":3.0}''
```

### Add a point light at world origin
```
simplicio skill run unreal-engine-mcp call spawn_actor \
  ''{"class":"/Script/Engine.PointLight","location":{"x":0,"y":0,"z":300}}''
```

### Set directional light color
```
simplicio skill run unreal-engine-mcp call set_actor_property \
  ''{"actor":"DirectionalLight","property":"LightColor","value":{"r":255,"g":240,"b":200}}''
```

## Material Examples

### Create a material instance
```
simplicio skill run unreal-engine-mcp call create_material_instance \
  ''{"parent":"/Game/Materials/M_Base","name":"MI_Rock"}''
```

### Set a scalar parameter
```
simplicio skill run unreal-engine-mcp call set_material_parameter \
  ''{"instance":"/Game/Materials/MI_Rock","parameter":"Roughness","value":0.7}''
```

### Apply material to actor
```
simplicio skill run unreal-engine-mcp call set_actor_material \
  ''{"actor":"SM_Rock_01","slot":0,"material":"/Game/Materials/MI_Rock"}''
```

## Custom Endpoint

If you changed the port or path in Editor Preferences:

```
simplicio skill run unreal-engine-mcp --url http://127.0.0.1:9090/mcp ping
```

## Tool Discovery

To see all tools the running editor exposes:

```
simplicio skill run unreal-engine-mcp call list_tools ''{}''
```

The exact tool surface depends on which toolsets are enabled in your project.

## Notes and Pitfalls

- The server runs tool calls **serially on the engine game thread** — do not
  issue overlapping calls; wait for','.simplicio-loop\skills\unreal-engine-mcp\SKILL.md','9b2759a3145ec22a3cc70696b4a6ff65012cf1dea80a9817351c3f415f912b79','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:using-superpowers','project_skill','skill://simplicio-runtime/using-superpowers','skill: using-superpowers','---
name: using-superpowers
description: Use when starting any conversation - establishes how to find and use skills, requiring Skill tool invocation before ANY response including clarifying questions
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, skip this skill.
</SUBAGENT-STOP>

<EXTREMELY-IMPORTANT>
If you think there is even a 1% chance a skill might apply to what you are doing, you ABSOLUTELY MUST invoke the skill.

IF A SKILL APPLIES TO YOUR TASK, YOU DO NOT HAVE A CHOICE. YOU MUST USE IT.

This is not negotiable. This is not optional. You cannot rationalize your way out of this.
</EXTREMELY-IMPORTANT>

## Instruction Priority

Superpowers skills override default system prompt behavior, but **user instructions always take precedence**:

1. **User''s explicit instructions** (CLAUDE.md, GEMINI.md, AGENTS.md, direct requests) — highest priority
2. **Superpowers skills** — override default system behavior where they conflict
3. **Default system prompt** — lowest priority

If CLAUDE.md, GEMINI.md, or AGENTS.md says "don''t use TDD" and a skill says "always use TDD," follow the user''s instructions. The user is in control.

## How to Access Skills

**In Claude Code:** Use the `Skill` tool. When you invoke a skill, its content is loaded and presented to you—follow it directly. Never use the Read tool on skill files.

**In Copilot CLI:** Use the `skill` tool. Skills are auto-discovered from installed plugins. The `skill` tool works the same as Claude Code''s `Skill` tool.

**In Gemini CLI:** Skills activate via the `activate_skill` tool. Gemini loads skill metadata at session start and activates the full content on demand.

**In other environments:** Check your platform''s documentation for how skills are loaded.

## Platform Adaptation

Skills use Claude Code tool names. Non-CC platforms: see `references/copilot-tools.md` (Copilot CLI), `references/codex-tools.md` (Codex) for tool equivalents. Gemini CLI users get the tool mapping loaded automatically via GEMINI.md.

# Using Skills

## The Rule

**Invoke relevant or requested skills BEFORE any response or action.** Even a 1% chance a skill might apply means that you should invoke the skill to check. If an invoked skill turns out to be wrong for the situation, you don''t need to use it.

```dot
digraph skill_flow {
    "User message received" [shape=doublecircle];
    "About to EnterPlanMode?" [shape=doublecircle];
    "Already brainstormed?" [shape=diamond];
    "Invoke brainstorming skill" [shape=box];
    "Might any skill apply?" [shape=diamond];
    "Invoke Skill tool" [shape=box];
    "Announce: ''Using [skill] to [purpose]''" [shape=box];
    "Has checklist?" [shape=diamond];
    "Create TodoWrite todo per item" [shape=box];
    "Follow skill exactly" [shape=box];
    "Respond (including clarifications)" [shape=doublecircle];

    "About to EnterPlanMode?" -> "Already brainstormed?";
    "Already brainstormed?" -> "Invoke brainstorming skill" [label="no"];
    "Already brainstormed?" -> "Might any skill apply?" [label="yes"];
    "Invoke brainstorming skill" -> "Might any skill apply?";

    "User message received" -> "Might any skill apply?";
    "Might any skill apply?" -> "Invoke Skill tool" [label="yes, even 1%"];
    "Might any skill apply?" -> "Respond (including clarifications)" [label="definitely not"];
    "Invoke Skill tool" -> "Announce: ''Using [skill] to [purpose]''";
    "Announce: ''Using [skill] to [purpose]''" -> "Has checklist?";
    "Has checklist?" -> "Create TodoWrite todo per item" [label="yes"];
    "Has checklist?" -> "Follow skill exactly" [label="no"];
    "Create TodoWrite todo per item" -> "Follow skill exactly";
}
```

## Red Flags

These thoughts mean STOP—you''re rationalizing:

| Thought | Reality |
|---------|---------|
| "This is just a simple question" | Questions are tasks. Check for skills. |
| "I need more context first" | Skill check comes BEFORE clarifying questions. |
| "Let me explore the codebase first" | Skills tell you HOW to explore. Check first. |
| "I can check git/files quickly" | Files lack ','.simplicio-loop\skills\using-superpowers\SKILL.md','68b1504ab97eb25a633426f6a44e0f93150a0de9c2c5293029a515d63cbaf1c0','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:verification-before-completion','project_skill','skill://simplicio-runtime/verification-before-completion','skill: verification-before-completion','---
name: verification-before-completion
description: Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success claims; evidence before assertions always
---

# Verification Before Completion

## Overview

Claiming work is complete without verification is dishonesty, not efficiency.

**Core principle:** Evidence before claims, always.

**Violating the letter of this rule is violating the spirit of this rule.**

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven''t run the verification command in this message, you cannot claim it passes.

## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN: Execute the FULL command (fresh, complete)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does output confirm the claim?
   - If NO: State actual status with evidence
   - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```

## Common Failures

| Claim | Requires | Not Sufficient |
|-------|----------|----------------|
| Tests pass | Test command output: 0 failures | Previous run, "should pass" |
| Linter clean | Linter output: 0 errors | Partial check, extrapolation |
| Build succeeds | Build command: exit 0 | Linter passing, logs look good |
| Bug fixed | Test original symptom: passes | Code changed, assumed fixed |
| Regression test works | Red-green cycle verified | Test passes once |
| Agent completed | VCS diff shows changes | Agent reports "success" |
| Requirements met | Line-by-line checklist | Tests passing |

## Red Flags - STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!", etc.)
- About to commit/push/PR without verification
- Trusting agent success reports
- Relying on partial verification
- Thinking "just this once"
- Tired and wanting work over
- **ANY wording implying success without having run verification**

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Should work now" | RUN the verification |
| "I''m confident" | Confidence ≠ evidence |
| "Just this once" | No exceptions |
| "Linter passed" | Linter ≠ compiler |
| "Agent said success" | Verify independently |
| "I''m tired" | Exhaustion ≠ excuse |
| "Partial check is enough" | Partial proves nothing |
| "Different words so rule doesn''t apply" | Spirit over letter |

## Key Patterns

**Tests:**
```
✅ [Run test command] [See: 34/34 pass] "All tests pass"
❌ "Should pass now" / "Looks correct"
```

**Regression tests (TDD Red-Green):**
```
✅ Write → Run (pass) → Revert fix → Run (MUST FAIL) → Restore → Run (pass)
❌ "I''ve written a regression test" (without red-green verification)
```

**Build:**
```
✅ [Run build] [See: exit 0] "Build passes"
❌ "Linter passed" (linter doesn''t check compilation)
```

**Requirements:**
```
✅ Re-read plan → Create checklist → Verify each → Report gaps or completion
❌ "Tests pass, phase complete"
```

**Agent delegation:**
```
✅ Agent reports success → Check VCS diff → Verify changes → Report actual state
❌ Trust agent report
```

## Why This Matters

From 24 failure memories:
- your human partner said "I don''t believe you" - trust broken
- Undefined functions shipped - would crash
- Missing requirements shipped - incomplete features
- Time wasted on false completion → redirect → rework
- Violates: "Honesty is a core value. If you lie, you''ll be replaced."

## When To Apply

**ALWAYS before:**
- ANY variation of success/completion claims
- ANY expression of satisfaction
- ANY positive statement about work state
- Committing, PR creation, task completion
- Moving to next task
- Delegating to agents

**Rule applies to:**
- Exact phrases
- Paraphrases and synonyms
- Implications of success
- ANY communication suggesting completion/correctness

## The Bottom Line

**No shortcuts for verification.**

Run the command. Read the out','.simplicio-loop\skills\verification-before-completion\SKILL.md','97b00936d335c70410f7df9c405800244c23929e0f56e66985db4a7fffdbe2bd','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:viral-product-strategist','project_skill','skill://simplicio-runtime/viral-product-strategist','skill: viral-product-strategist','---
name: viral-product-strategist
description: Activates for product, SaaS, app, course, CLI, offer, pricing, launch, conversion, copywriting, positioning, hero section, CTA, paywall, testimonial, OG image, footer, and landing page/LP work. Use when the user wants to audit an existing LP, improve conversion, make a product more viral, rewrite sales copy, strengthen an offer, simplify pricing, compare competitors, or apply the 32 principles of viral products.
---

# Viral Product Strategist

Use this skill when the user wants to create, improve, audit, reposition, launch, or rewrite a product, landing page, SaaS, digital product, app, CLI, course, template, community, marketplace, or marketing asset using viral-product principles.

The skill is based on the idea that viral products are not merely “good products”. They are products that are easy to understand, easy to remember, easy to talk about, easy to buy, and easy to share.

The 32 principles are patterns, not laws. Use them as a compass. Apply judgment based on product type, market, audience, price point, proof available, and business model.

## Core job

Help the user turn a product into something people can understand in seconds, remember the next day, want to try, trust enough to buy, and feel compelled to share.

The skill can produce:

- Viral product audit
- Landing page rewrite
- Hero section rewrite
- Pricing strategy
- Product positioning
- Paywall strategy
- Demo/try-before-buy strategy
- OG image concept
- Footer/share ending
- Launch checklist
- Viral product scorecard
- Copy variants
- Competitor comparison table
- Testimonial collection plan
- Product naming critique

## When to invoke

Invoke this skill when the user asks for help with any of the following:

- “Make this product more viral”
- “Audit my landing page”
- “Improve my SaaS positioning”
- “Rewrite my hero section”
- “Create a landing page for this product”
- “Help me price this product”
- “Make this product easier to sell”
- “Create copy for launch”
- “Make my offer stronger”
- “Analyze this product idea”
- “Improve conversion”
- “Create a SKILL/playbook for viral products”
- “Apply the 32 principles of viral products”

Do not invoke it for unrelated product work such as backend architecture, legal compliance, financial modeling, or technical implementation unless the user explicitly wants the viral-product/marketing angle.

## Required inputs

Ask for missing inputs only when they materially change the answer. If the user gives partial information, proceed with clearly labeled assumptions.

Ideal inputs:

1. Product name
2. Product type: SaaS, app, course, template, CLI, marketplace, service, plugin, physical product, etc.
3. Target customer
4. Pain/desire the product solves
5. Current landing page copy or URL, if available
6. Pricing model and price
7. Main competitors or alternatives
8. Current proof: testimonials, revenue, users, case studies, waitlist, demos, screenshots
9. Main conversion goal: buy, analyze, generate, book call, join waitlist, install, upload file, etc.
10. Distribution channel: X/Twitter, LinkedIn, Instagram, SEO, Product Hunt, ads, communities, influencers, founder audience, cold outbound, etc.

Minimum viable input:

- What the product does
- Who it is for
- What the user wants improved

If even the minimum is missing, ask for a compact clarification:

“Me manda em 1 frase: o que o produto faz, pra quem é, e qual ação você quer que a pessoa tome.”

## Operating principles

Follow these rules while using the skill:

1. Be direct, concrete, and opinionated.
2. Prefer clear claims over vague praise.
3. Replace adjectives with numbers whenever possible.
4. If numbers are unknown, use placeholders or suggest what to measure. Do not invent metrics.
5. Treat the hero section as the highest-leverage surface.
6. Treat the product demo as more persuasive than explanation.
7. Reduce choices. One product promise. One main CTA. Three pricing options max.
8. Make the product easy to describe in under 10 words.
9. Make the copy sound like the founder or customer, not a corporate ','.simplicio-loop\skills\viral-product-strategist\SKILL.md','4aa19f8f9378aff38fe316fa5d44114fdaa679b55001556098e70bba235455b6','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:waapi','project_skill','skill://simplicio-runtime/waapi','skill: waapi','---
name: waapi
description: Web Animations API adapter patterns for HyperFrames. Use when authoring element.animate() motion, Animation currentTime seeking, document.getAnimations(), KeyframeEffect timing, fill modes, or native browser animations that must render deterministically in HyperFrames.
---

# Web Animations API for HyperFrames

HyperFrames can seek Web Animations API animations through its `waapi` runtime adapter. WAAPI is useful when you want native browser keyframes with JavaScript-created timing and no GSAP dependency.

## Contract

- Create animations synchronously during composition initialization.
- Use `element.animate(...)` with finite `duration` and `iterations`.
- Use `fill: "both"` so seeked states persist.
- Pause animations after creation or let the adapter pause them on first seek.
- Avoid callbacks and promises for render-critical state.

The adapter calls `document.getAnimations()`, sets each animation''s `currentTime` to HyperFrames time in milliseconds, then pauses it.

## Basic Pattern

```html
<div id="orb" class="clip orb" data-start="2" data-duration="3" data-track-index="2"></div>

<script>
  const orb = document.getElementById("orb");
  const animation = orb.animate(
    [
      { transform: "translate3d(-160px, 0, 0) scale(0.8)", opacity: 0 },
      { transform: "translate3d(0, 0, 0) scale(1)", opacity: 1, offset: 0.35 },
      { transform: "translate3d(120px, 0, 0) scale(1.08)", opacity: 1 },
    ],
    {
      duration: 3000,
      delay: 2000,
      easing: "cubic-bezier(0.2, 0, 0, 1)",
      fill: "both",
      iterations: 1,
    },
  );

  animation.pause();
</script>
```

## Stagger Pattern

```js
document.querySelectorAll(".token").forEach((token, index) => {
  const animation = token.animate(
    [
      { transform: "translateY(24px)", opacity: 0 },
      { transform: "translateY(0)", opacity: 1 },
    ],
    {
      duration: 620,
      delay: index * 80,
      easing: "cubic-bezier(0.2, 0, 0, 1)",
      fill: "both",
      iterations: 1,
    },
  );
  animation.pause();
});
```

## Good Uses

- Lightweight DOM motion where CSS keyframes are too rigid and GSAP is unnecessary.
- Generated animations from structured data.
- Simple timelines that can be represented as keyframes, delays, and offsets.

## Avoid

- Infinite `iterations`.
- Depending on `animation.finished` to mutate render-critical DOM.
- Running separate clocks with `requestAnimationFrame`, timers, or `performance.now()`.
- Animating layout properties when transforms and opacity can express the motion.
- Assuming clip-local start time is automatic. WAAPI adapter seeks document-level animation time; model clip offsets with `delay` or create the animation on an element whose visibility is controlled by HyperFrames timing.

## Validation

After editing a WAAPI composition:

```bash
npx hyperframes lint
npx hyperframes validate
```

## Credits And References

- HyperFrames adapter source: `packages/core/src/runtime/adapters/waapi.ts`.
- MDN Web Animations API guide: https://developer.mozilla.org/docs/Web/API/Web_Animations_API/Using_the_Web_Animations_API
- MDN `Animation.currentTime`: https://developer.mozilla.org/en-US/docs/Web/API/Animation/currentTime
','.simplicio-loop\skills\waapi\SKILL.md','e465beaf82a4f2de0fc40c705bdddddf59d851fc96ebb339c931ed9458d30cfb','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:watchers','project_skill','skill://simplicio-runtime/watchers','skill: watchers','---
name: watchers
description: Poll RSS, JSON APIs, and GitHub with watermark dedup.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [cron, polling, rss, github, http, automation, monitoring]
    category: devops
    requires_toolsets: [terminal]
    related_skills: []
---

# Watchers

Poll external sources on an interval and react only to new items. Three ready-made scripts plus a shared watermark helper; wire them into a cron job (or run them ad-hoc from the terminal).

## When to Use

- User wants to watch an RSS/Atom feed and be notified of new entries
- User wants to watch a GitHub repo''s issues / pulls / releases / commits
- User wants to poll an arbitrary JSON endpoint and get notified on new items
- User asks for "a watcher for X" or "notify me when X changes"

## Mental model

A watcher is just a script that:

1. Fetches data from the external source
2. Compares against a watermark file of previously-seen IDs
3. Writes the new watermark back
4. Prints new items to stdout (or nothing on no-change)

The scripts below handle all three. The agent runs them via the terminal tool — from a cron job, a webhook, or an interactive chat — and reports what''s new.

## Ready-made scripts

All three live in `$HERMES_HOME/skills/devops/watchers/scripts/` once the skill is installed. Each reads `WATCHER_STATE_DIR` (defaults to `$HERMES_HOME/watcher-state/`) for its state file, keyed by the `--name` argument.

| Script | What it watches | Dedup key |
|---|---|---|
| `watch_rss.py` | RSS 2.0 or Atom feed URL | `<guid>` / `<id>` |
| `watch_http_json.py` | Any JSON endpoint returning a list of objects | Configurable id field |
| `watch_github.py` | GitHub issues / pulls / releases / commits for a repo | `id` / `sha` |

All three:

- First run records a baseline — never replays existing feed
- Watermark is a bounded ID set (max 500) to cap memory
- Output format: `## <title>\n<url>\n\n<optional body>` per item
- Empty stdout on no-new — the caller treats that as silent
- Non-zero exit on fetch errors

## Usage

Run a watcher directly from the terminal tool:

```bash
python $HERMES_HOME/skills/devops/watchers/scripts/watch_rss.py \
  --name hn --url https://news.ycombinator.com/rss --max 5
```

Watch a GitHub repo (set `GITHUB_TOKEN` in `${HERMES_HOME:-~/.hermes}/.env` to avoid the 60 req/hr anonymous rate limit):

```bash
python $HERMES_HOME/skills/devops/watchers/scripts/watch_github.py \
  --name hermes-issues --repo NousResearch/hermes-agent --scope issues
```

Poll an arbitrary JSON API:

```bash
python $HERMES_HOME/skills/devops/watchers/scripts/watch_http_json.py \
  --name api --url https://api.example.com/events \
  --id-field event_id --items-path data.events
```

## Wiring into cron

Ask the agent to schedule a cron job with a prompt like:

> Every 15 minutes, run `watch_rss.py --name hn --url https://news.ycombinator.com/rss`. If it prints anything, summarize the headlines and deliver them. If it prints nothing, stay silent.

The agent invokes the script via the terminal tool inside the cron job''s agent loop; no changes to cron''s built-in `--script` flag are needed.

## State files

Every watcher writes `$HERMES_HOME/watcher-state/<name>.json`. Inspect:

```bash
cat $HERMES_HOME/watcher-state/hn.json
```

Force a replay (next run treated as first poll):

```bash
rm $HERMES_HOME/watcher-state/hn.json
```

## Writing your own

All three scripts use the same template: load watermark, fetch, diff, save, emit. `scripts/_watermark.py` is the shared helper; import it to get atomic writes + bounded ID set + first-run baseline for free. See any of the three reference scripts for how little boilerplate it takes.

## Common Pitfalls

1. **Printing a "no new items" header every tick.** Callers rely on empty stdout = silent. If you print anything on an empty delta, you spam the channel. The shipped scripts handle this; custom scripts must too.
2. **Expecting the first run to emit items.** It won''t — first run records a baseline. If you need an initial digest, delete the state fi','.simplicio-loop\skills\watchers\SKILL.md','2bb720761bdc0648ed6f02792d005ded2c611c36392f5239a73bd9e746227428','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:web-pentest','project_skill','skill://simplicio-runtime/web-pentest','skill: web-pentest','---
name: web-pentest
description: |
  Authorized web application penetration testing — reconnaissance, vulnerability
  analysis, proof-based exploitation, and professional reporting. Adapts
  Shannon''s "No Exploit, No Report" methodology with hard guardrails for
  scope, authorization, and aux-client leakage. Active testing against running
  applications you own or have written authorization to test.
platforms: [linux, macos]
category: security
triggers:
  - "pentest [URL]"
  - "pentest this app"
  - "penetration test [URL]"
  - "security test this web app"
  - "test [URL] for vulnerabilities"
  - "find vulns in [URL]"
  - "OWASP test [URL]"
toolsets:
  - terminal
  - web
  - browser
  - file
  - delegation
---

# Web Application Penetration Testing

A phased pentesting workflow for running web applications. Adapted from
Shannon''s pipeline (Keygraph, AGPL — concepts only, no code borrowed).
Built around three rules:

1. No exploit, no report — every finding requires reproducible evidence.
2. Bounded scope — every active request goes against a target the operator
   pre-declared. Off-scope hosts are refused.
3. Bypass exhaustion before false-positive dismissal — a "blocked" payload
   is not a clean bill of health until you''ve tried the bypass set.

---

## ⚠️ Hard Guardrails — Read Before Every Engagement

Violating any of these invalidates the engagement and may be illegal.

1. **Authorization gate.** Before the first active scan in a session, you
   MUST confirm with the user, in writing, that they own or have written
   authorization to test the target. Record the acknowledgement in
   `engagement/authorization.md` (see template). No acknowledgement → no
   active scanning. Reading public pages with `curl` is fine; sending
   payloads is not.

2. **Scope allowlist.** Maintain `engagement/scope.txt` — one hostname or
   CIDR per line. Every `nmap`, `curl`, `whatweb`, browser navigation, or
   payload-bearing request MUST be against an entry in scope. If a target
   redirects you off-scope (3xx to a different host, a link in HTML),
   STOP and confirm with the user before following.

3. **No production systems without paper.** If the user hasn''t told you
   "yes, prod is in scope and I have written sign-off," assume not. Default
   targets are staging, local docker, dedicated test instances.

4. **Cloud metadata is off by default.** Do not probe `169.254.169.254`,
   `metadata.google.internal`, `100.100.100.200`, `[fd00:ec2::254]`, or
   equivalent unless the engagement explicitly includes SSRF-to-metadata
   as a goal AND the target is one you control. The agent''s browser tool
   can reach these from inside your own infrastructure — don''t.

5. **Destructive payloads need approval.** SQLi payloads that DROP/DELETE,
   filesystem-write SSTI, command injection with `rm`/`shutdown`/`mkfs`,
   anything that mutates beyond a single test row → ASK FIRST. The
   `approval.py` system catches some; don''t rely on it alone.

6. **Aux-client leakage risk (Hermes-specific).** This skill produces
   sessions full of SQLi/XSS/RCE payloads, captured credentials, JWT
   tokens. Hermes'' compression and title-generation paths replay history
   through the auxiliary client (often the main model). Anything sensitive
   you write to the conversation can leave the box on the next compress.
   Mitigation:
   - Redact captured tokens/credentials to the LAST 6 CHARS before logging
     them in any message. Full values go to `engagement/evidence/` files,
     never into chat history.
   - If the engagement is sensitive, set `auxiliary.title_generation.enabled: false`
     in `~/.hermes/config.yaml` for the session.

7. **Rate limit yourself.** Default 200ms between active requests against
   any single host. The recon-scan.sh script enforces this. Don''t bypass
   it without operator approval.

8. **Authority of the report.** This skill produces a security
   assessment, not a "PASS." Even a clean run is "no exploitable issues
   FOUND in scope X within time T using methods Y" — not "the application
   is secure." Mirror that language in the repo','.simplicio-loop\skills\web-pentest\SKILL.md','3706fe253a37950b4a1bb4f1d1633e33e8ad4f5f149757b08da6107e9dfed020','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:website-to-hyperframes','project_skill','skill://simplicio-runtime/website-to-hyperframes','skill: website-to-hyperframes','---
name: website-to-hyperframes
description: |
  Capture a website and create a HyperFrames video from it. Use when: (1) a user provides a URL and wants a video, (2) someone says "capture this site", "turn this into a video", "make a promo from my site", (3) the user wants a social ad, product tour, or any video based on an existing website, (4) the user shares a link and asks for any kind of video content. Even if the user just pastes a URL — this is the skill to use.
---

# Website to HyperFrames

Capture a website, then produce a professional video from it.

Users say things like:

- "Capture https://... and make me a 25-second product launch video"
- "Turn this website into a 15-second social ad for Instagram"
- "Create a 30-second product tour from https://..."

The workflow has 7 steps. Each produces an artifact that gates the next. By default it''s collaborative — gates marked 💬 stop and ask the user. If the user signals autonomous mode ("decide for me", "surprise me"), every 💬 gate is skipped; see step-2-brief.md for how that propagates.

---

## Step 0: Capture & Understand the Brand

**Read:** [references/step-0-capture.md](references/step-0-capture.md)

Capture the site, then read the extracted data to understand the **brand and product** — what it does, who it''s for, what voice it speaks in, what mood it lives in. The captured assets are a brand toolkit for later, not the building blocks the video is made from.

**Gate:** Site summary printed — strategy-first (what the product does, who it''s for, brand voice) before the asset / color / font inventory.

---

## Step 1: Brand Identity

**Read:** [references/step-1-design.md](references/step-1-design.md)

Write DESIGN.md — a brand cheat sheet covering the visual identity: colors, typography, component styles, layout principles. Use `design-styles.json` for exact computed values.

**Speed option:** For fast-pacing videos (billboard-per-beat), DESIGN.md can be a 50-line summary of colors + fonts + do''s/don''ts — not a 300-line document. The sub-agent prompt in Step 5 pastes brand values directly, so DESIGN.md depth only matters for complex compositions.

**Gate:** `DESIGN.md` exists (any length) with at minimum: color palette, font choices, and do''s/don''ts.

---

## Step 2: Strategy & Messaging

**Read:** [references/step-2-brief.md](references/step-2-brief.md), [references/capabilities.md](references/capabilities.md) (scan the Table of Contents — deep-dive sections only as needed)

Align with the user on **what the video must communicate** before talking visuals or assets. Parse the user''s prompt — they probably already gave you the video type and style. Ask only what''s missing: the ONE thing this video must say, the narrative arc, and the audience.

**Gate:** Video type, duration, format, and — critically — the message and narrative arc are locked. Without those, Step 3 can''t write a concept-first storyboard.

---

## Step 3: Storyboard + Script 💬

**Read:** [references/step-3-storyboard.md](references/step-3-storyboard.md)

Write the storyboard concept-first: message → narrative arc → beats that serve the arc → techniques per beat → brand accents pass at the end. Then write the narration script to match. Present both to the user with a beat-by-beat summary. Iterate until they approve.

**Gate:** `STORYBOARD.md` + `SCRIPT.md` exist AND the user has approved the plan.

---

## Step 4: VO, Timing + Captions 💬

**Read:** [references/step-4-vo.md](references/step-4-vo.md)

If Step 2 said no narration — ask about background music, then skip to Step 5. Otherwise: ask the user which TTS provider (HeyGen TTS, ElevenLabs, or Kokoro), generate audio, transcribe, map timestamps to beats. Then ask about captions.

**Gate:** Either (a) no narration was requested and storyboard has manual beat timings, or (b) `narration.wav` + `transcript.json` exist and beat timings updated with real durations.

---

## Step 5: Build Compositions

**Read:** The `hyperframes` skill (load it — every rule matters)
**Read:** [references/step-5-build.md](references/step-5-build.md)

Build index.ht','.simplicio-loop\skills\website-to-hyperframes\SKILL.md','25046dbd4bfbf2cbead22b29d1e89b69a79710955c8e779ac7ebe62484202bfa','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:whisper','project_skill','skill://simplicio-runtime/whisper','skill: whisper','---
name: whisper
description: OpenAI''s general-purpose speech recognition model. Supports 99 languages, transcription, translation to English, and language identification. Six model sizes from tiny (39M params) to large (1550M params). Use for speech-to-text, podcast transcription, or multilingual audio processing. Best for robust, multilingual ASR.
version: 1.0.0
author: Orchestra Research
license: MIT
dependencies: [openai-whisper, transformers, torch]
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Whisper, Speech Recognition, ASR, Multimodal, Multilingual, OpenAI, Speech-To-Text, Transcription, Translation, Audio Processing]

---

# Whisper - Robust Speech Recognition

OpenAI''s multilingual speech recognition model.

## When to use Whisper

**Use when:**
- Speech-to-text transcription (99 languages)
- Podcast/video transcription
- Meeting notes automation
- Translation to English
- Noisy audio transcription
- Multilingual audio processing

**Metrics**:
- **72,900+ GitHub stars**
- 99 languages supported
- Trained on 680,000 hours of audio
- MIT License

**Use alternatives instead**:
- **AssemblyAI**: Managed API, speaker diarization
- **Deepgram**: Real-time streaming ASR
- **Google Speech-to-Text**: Cloud-based

## Quick start

### Installation

```bash
# Requires Python 3.8-3.11
pip install -U openai-whisper

# Requires ffmpeg
# macOS: brew install ffmpeg
# Ubuntu: sudo apt install ffmpeg
# Windows: choco install ffmpeg
```

### Basic transcription

```python
import whisper

# Load model
model = whisper.load_model("base")

# Transcribe
result = model.transcribe("audio.mp3")

# Print text
print(result["text"])

# Access segments
for segment in result["segments"]:
    print(f"[{segment[''start'']:.2f}s - {segment[''end'']:.2f}s] {segment[''text'']}")
```

## Model sizes

```python
# Available models
models = ["tiny", "base", "small", "medium", "large", "turbo"]

# Load specific model
model = whisper.load_model("turbo")  # Fastest, good quality
```

| Model | Parameters | English-only | Multilingual | Speed | VRAM |
|-------|------------|--------------|--------------|-------|------|
| tiny | 39M | ✓ | ✓ | ~32x | ~1 GB |
| base | 74M | ✓ | ✓ | ~16x | ~1 GB |
| small | 244M | ✓ | ✓ | ~6x | ~2 GB |
| medium | 769M | ✓ | ✓ | ~2x | ~5 GB |
| large | 1550M | ✗ | ✓ | 1x | ~10 GB |
| turbo | 809M | ✗ | ✓ | ~8x | ~6 GB |

**Recommendation**: Use `turbo` for best speed/quality, `base` for prototyping

## Transcription options

### Language specification

```python
# Auto-detect language
result = model.transcribe("audio.mp3")

# Specify language (faster)
result = model.transcribe("audio.mp3", language="en")

# Supported: en, es, fr, de, it, pt, ru, ja, ko, zh, and 89 more
```

### Task selection

```python
# Transcription (default)
result = model.transcribe("audio.mp3", task="transcribe")

# Translation to English
result = model.transcribe("spanish.mp3", task="translate")
# Input: Spanish audio → Output: English text
```

### Initial prompt

```python
# Improve accuracy with context
result = model.transcribe(
    "audio.mp3",
    initial_prompt="This is a technical podcast about machine learning and AI."
)

# Helps with:
# - Technical terms
# - Proper nouns
# - Domain-specific vocabulary
```

### Timestamps

```python
# Word-level timestamps
result = model.transcribe("audio.mp3", word_timestamps=True)

for segment in result["segments"]:
    for word in segment["words"]:
        print(f"{word[''word'']} ({word[''start'']:.2f}s - {word[''end'']:.2f}s)")
```

### Temperature fallback

```python
# Retry with different temperatures if confidence low
result = model.transcribe(
    "audio.mp3",
    temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
)
```

## Command line usage

```bash
# Basic transcription
whisper audio.mp3

# Specify model
whisper audio.mp3 --model turbo

# Output formats
whisper audio.mp3 --output_format txt     # Plain text
whisper audio.mp3 --output_format srt     # Subtitles
whisper audio.mp3 --output_format vtt     # WebVTT
whisper audio.mp3 --output_format json    # JSON with timestamps

# Language
whisper audio.mp3 --la','.simplicio-loop\skills\whisper\SKILL.md','0f894a20dc46da0ed6c62489478c82d928cc5ec4f5739c5cbdc3bb66eee35eba','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:writing-plans','project_skill','skill://simplicio-runtime/writing-plans','skill: writing-plans','---
name: writing-plans
description: Use when you have a spec or requirements for a multi-step task, before touching code
---

# Writing Plans

## Overview

Write comprehensive implementation plans assuming the engineer has zero context for our codebase and questionable taste. Document everything they need to know: which files to touch for each task, code, testing, docs they might need to check, how to test it. Give them the whole plan as bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume they are a skilled developer, but know almost nothing about our toolset or problem domain. Assume they don''t know good test design very well.

**Announce at start:** "I''m using the writing-plans skill to create the implementation plan."

**Context:** If working in an isolated worktree, it should have been created via the `superpowers:using-git-worktrees` skill at execution time.

**Save plans to:** `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md`
- (User preferences for plan location override this default)

## Scope Check

If the spec covers multiple independent subsystems, it should have been broken into sub-project specs during brainstorming. If it wasn''t, suggest breaking this into separate plans — one per subsystem. Each plan should produce working, testable software on its own.

## File Structure

Before defining tasks, map out which files will be created or modified and what each one is responsible for. This is where decomposition decisions get locked in.

- Design units with clear boundaries and well-defined interfaces. Each file should have one clear responsibility.
- You reason best about code you can hold in context at once, and your edits are more reliable when files are focused. Prefer smaller, focused files over large ones that do too much.
- Files that change together should live together. Split by responsibility, not by technical layer.
- In existing codebases, follow established patterns. If the codebase uses large files, don''t unilaterally restructure - but if a file you''re modifying has grown unwieldy, including a split in the plan is reasonable.

This structure informs the task decomposition. Each task should produce self-contained changes that make sense independently.

## Bite-Sized Task Granularity

**Each step is one action (2-5 minutes):**
- "Write the failing test" - step
- "Run it to make sure it fails" - step
- "Implement the minimal code to make the test pass" - step
- "Run the tests and make sure they pass" - step
- "Commit" - step

## Plan Document Header

**Every plan MUST start with this header:**

```markdown
# [Feature Name] Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

## Task Structure

````markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

## No Placeholders

Every step must contain the actual content an engineer needs. These are **plan failures** — never write them:
- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "add validation" / "handle edge cases"
- "Wri','.simplicio-loop\skills\writing-plans\SKILL.md','15a5ca28ce1bcc62b06edb295042e146cb9deaa5b35afb39f6be2cb9d068eeeb','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:xurl','project_skill','skill://simplicio-runtime/xurl','skill: xurl','---
name: xurl
description: "X/Twitter via xurl CLI: post, search, DM, media, v2 API."
version: 1.1.1
author: xdevplatform + openclaw + Hermes Agent
license: MIT
platforms: [linux, macos]
prerequisites:
  commands: [xurl]
metadata:
  hermes:
    tags: [twitter, x, social-media, xurl, official-api]
    homepage: https://github.com/xdevplatform/xurl
    upstream_skill: https://github.com/openclaw/openclaw/blob/main/skills/xurl/SKILL.md
---

# xurl — X (Twitter) API via the Official CLI

`xurl` is the X developer platform''s official CLI for the X API. It supports shortcut commands for common actions AND raw curl-style access to any v2 endpoint. All commands return JSON to stdout.

Use this skill for:
- posting, replying, quoting, deleting posts
- searching posts and reading timelines/mentions
- liking, reposting, bookmarking
- following, unfollowing, blocking, muting
- direct messages
- media uploads (images and video)
- raw access to any X API v2 endpoint
- multi-app / multi-account workflows

This skill replaces the older `xitter` skill (which wrapped a third-party Python CLI). `xurl` is maintained by the X developer platform team, supports OAuth 2.0 PKCE with auto-refresh, and covers a substantially larger API surface.

---

## Secret Safety (MANDATORY)

Critical rules when operating inside an agent/LLM session:

- **Never** read, print, parse, summarize, upload, or send `~/.xurl` to LLM context.
- **Never** ask the user to paste credentials/tokens into chat.
- The user must fill `~/.xurl` with secrets manually on their own machine. In Docker, this must be the `~` seen by Hermes tool subprocesses; see the Docker note below.
- **Never** recommend or execute auth commands with inline secrets in agent sessions.
- **Never** use `--verbose` / `-v` in agent sessions — it can expose auth headers/tokens.
- To verify credentials exist, only use: `xurl auth status`.

Forbidden flags in agent commands (they accept inline secrets):
`--bearer-token`, `--consumer-key`, `--consumer-secret`, `--access-token`, `--token-secret`, `--client-id`, `--client-secret`

App credential registration and credential rotation must be done by the user manually, outside the agent session. After credentials are registered, the user authenticates with `xurl auth oauth2` — also outside the agent session. Tokens persist to `~/.xurl` in YAML. Each app has isolated tokens. OAuth 2.0 tokens auto-refresh.

---

## Installation

Pick ONE method. On Linux, the shell script or `go install` are the easiest.

```bash
# Shell script (installs to ~/.local/bin, no sudo, works on Linux + macOS)
curl -fsSL https://raw.githubusercontent.com/xdevplatform/xurl/main/install.sh | bash

# Homebrew (macOS)
brew install --cask xdevplatform/tap/xurl

# npm
npm install -g @xdevplatform/xurl

# Go
go install github.com/xdevplatform/xurl@latest
```

Verify:

```bash
xurl --help
xurl auth status
```

If `xurl` is installed but `auth status` shows no apps or tokens, the user needs to complete auth manually — see the next section.

---

## One-Time User Setup (user runs these outside the agent)

These steps must be performed by the user directly, NOT by the agent, because they involve pasting secrets. Direct the user to this block; do not execute it for them.

1. Create or open an app at https://developer.x.com/en/portal/dashboard
2. Set the redirect URI to `http://localhost:8080/callback`
3. Copy the app''s Client ID and Client Secret
4. Register the app locally (user runs this):
   ```bash
   xurl auth apps add my-app --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET
   ```
5. Authenticate (specify `--app` to bind the token to your app):
   ```bash
   xurl auth oauth2 --app my-app
   ```
   (This opens a browser for the OAuth 2.0 PKCE flow.)

   If X returns a `UsernameNotFound` error or 403 on the post-OAuth `/2/users/me` lookup, pass your handle explicitly (xurl v1.1.0+):
   ```bash
   xurl auth oauth2 --app my-app YOUR_USERNAME
   ```
   This binds the token to your handle and skips the broken `/2/users/me` call.
6. Set the app as default so all commands use it:
   ```b','.simplicio-loop\skills\xurl\SKILL.md','1203af39ff56874b2bfd05688272f569f5648fd2bb3ddf086ff7d0e027b177ff','skill,simplicio,content',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:youtube-content','project_skill','skill://simplicio-runtime/youtube-content','skill: youtube-content','---
name: youtube-content
description: "YouTube transcripts to summaries, threads, blogs."
platforms: [linux, macos, windows]
---

# YouTube Content Tool

## When to use

Use when the user shares a YouTube URL or video link, asks to summarize a video, requests a transcript, or wants to extract and reformat content from any YouTube video. Transforms transcripts into structured content (chapters, summaries, threads, blog posts).

Extract transcripts from YouTube videos and convert them into useful formats.

## Setup

```bash
pip install youtube-transcript-api
```

## Helper Script

`SKILL_DIR` is the directory containing this SKILL.md file. The script accepts any standard YouTube URL format, short links (youtu.be), shorts, embeds, live links, or a raw 11-character video ID.

```bash
# JSON output with metadata
python3 SKILL_DIR/scripts/fetch_transcript.py "https://youtube.com/watch?v=VIDEO_ID"

# Plain text (good for piping into further processing)
python3 SKILL_DIR/scripts/fetch_transcript.py "URL" --text-only

# With timestamps
python3 SKILL_DIR/scripts/fetch_transcript.py "URL" --timestamps

# Specific language with fallback chain
python3 SKILL_DIR/scripts/fetch_transcript.py "URL" --language tr,en
```

## Output Formats

After fetching the transcript, format it based on what the user asks for:

- **Chapters**: Group by topic shifts, output timestamped chapter list
- **Summary**: Concise 5-10 sentence overview of the entire video
- **Chapter summaries**: Chapters with a short paragraph summary for each
- **Thread**: Twitter/X thread format — numbered posts, each under 280 chars
- **Blog post**: Full article with title, sections, and key takeaways
- **Quotes**: Notable quotes with timestamps

### Example — Chapters Output

```
00:00 Introduction — host opens with the problem statement
03:45 Background — prior work and why existing solutions fall short
12:20 Core method — walkthrough of the proposed approach
24:10 Results — benchmark comparisons and key takeaways
31:55 Q&A — audience questions on scalability and next steps
```

## Workflow

1. **Fetch** the transcript using the helper script with `--text-only --timestamps`.
2. **Validate**: confirm the output is non-empty and in the expected language. If empty, retry without `--language` to get any available transcript. If still empty, tell the user the video likely has transcripts disabled.
3. **Chunk if needed**: if the transcript exceeds ~50K characters, split into overlapping chunks (~40K with 2K overlap) and summarize each chunk before merging.
4. **Transform** into the requested output format. If the user did not specify a format, default to a summary.
5. **Verify**: re-read the transformed output to check for coherence, correct timestamps, and completeness before presenting.

## Error Handling

- **Transcript disabled**: tell the user; suggest they check if subtitles are available on the video page.
- **Private/unavailable video**: relay the error and ask the user to verify the URL.
- **No matching language**: retry without `--language` to fetch any available transcript, then note the actual language to the user.
- **Dependency missing**: run `pip install youtube-transcript-api` and retry.
','.simplicio-loop\skills\youtube-content\SKILL.md','f6e573f84f3f62dadaa0839491d1558071b6e6da9db9878e7c765fe1311c66be','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:yuanbao','project_skill','skill://simplicio-runtime/yuanbao','skill: yuanbao','---
name: yuanbao
description: "Yuanbao (元宝) groups: @mention users, query info/members."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [yuanbao, mention, at, group, members, 元宝, 派, 艾特]
    related_skills: []
---

# Yuanbao Group Interaction

## CRITICAL: How Messaging Works

**Your text reply IS the message sent to the group/user.** The gateway automatically delivers your response text to the chat. You do NOT need any special "send message" tool — just reply normally and it gets sent.

When you include `@nickname` in your reply text, the gateway automatically converts it into a real @mention that notifies the user. This is built-in — you have full @mention capability.

**NEVER say you cannot send messages or @mention users. NEVER suggest the user do it manually. NEVER add disclaimers about permissions. Just reply with the text you want sent.**

## Available Tools

| Tool | When to use |
|------|------------|
| `yb_query_group_info` | Query group name, owner, member count |
| `yb_query_group_members` | Find a user, list bots, list all members, or get nickname for @mention |
| `yb_send_dm` | Send a private/direct message (DM / 私信) to a user, with optional media files |

## @Mention Workflow

When you need to @mention / 艾特 someone:

1. Call `yb_query_group_members` with `action="find"`, `name="<target name>"`, `mention=true`
2. Get the exact nickname from the response
3. Include `@nickname` in your reply text — the gateway handles the rest

Example: user says "帮我艾特元宝"

Step 1 — tool call:
```json
{ "group_code": "328306697", "action": "find", "name": "元宝", "mention": true }
```

Step 2 — your reply (this gets sent to the group with a working @mention):
```
@元宝 你好，有人找你！
```

**That''s it.** No extra explanation needed. Keep it short and natural.

**Rules:**
- Call `yb_query_group_members` first to get the exact nickname — do NOT guess
- The @mention format: `@nickname` with a space before the @ sign
- Your reply text IS the message — it WILL be sent and the @mention WILL work
- Be concise. Do NOT explain how @mention works to the user.

## Send DM (Private Message) Workflow

When someone asks to send a private message / 私信 / DM to a user:

1. Call `yb_send_dm` with `group_code`, `name` (target user''s name), and `message`
2. The tool automatically finds the user and sends the DM
3. Report the result to the user

Example: user says "给 @用户aea3 私信发一个 hello"

```json
yb_send_dm({ "group_code": "535168412", "name": "用户aea3", "message": "hello" })
```

Example with media: user says "给 @用户aea3 私信发一张图片"

```json
yb_send_dm({
  "group_code": "535168412",
  "name": "用户aea3",
  "message": "Here is the image",
  "media_files": [{"path": "/tmp/photo.jpg"}]
})
```

**Rules:**
- Extract `group_code` from the current chat_id (e.g. `group:535168412` → `535168412`)
- If you already know the user_id, pass it directly via the `user_id` parameter to skip lookup
- If multiple users match the name, the tool returns candidates — ask the user to clarify
- Do NOT use `send_message` tool for Yuanbao DMs — use `yb_send_dm` instead
- Supports media: images (.jpg/.png/.gif/.webp/.bmp) sent as image messages, other files as documents

## Query Group Info

```json
yb_query_group_info({ "group_code": "328306697" })
```

## Query Members

| Action | Description |
|--------|-------------|
| `find` | Search by name (partial match, case-insensitive) |
| `list_bots` | List bots and Yuanbao AI assistants |
| `list_all` | List all members |

## Notes

- `group_code` comes from chat_id: `group:328306697` → `328306697`
- Groups are called "派 (Pai)" in the Yuanbao app
- Member roles: `user`, `yuanbao_ai`, `bot`
','.simplicio-loop\skills\yuanbao\SKILL.md','239e4875f511124fab06e94ff21511fd8f857554c6ffd82dfb796ed275b4ff32','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:revisao-humanizada:.skills','project_skill','skill://simplicio-runtime/revisao-humanizada','skill: revisao-humanizada','---
name: revisao-humanizada
description: Revisa e reescreve textos para soarem humanos, naturais e conversacionais — removendo a "cara de IA". Use SEMPRE que o usuário pedir para revisar, humanizar, deixar natural, tirar cara de IA, reescrever, polir ou melhorar um texto, roteiro, post, legenda, e-mail, copy, artigo, script de YouTube, carrossel ou qualquer conteúdo escrito. Também acione em pedidos como "revisa esse texto", "tá com cara de ChatGPT", "deixa mais humano", "tira o ar de IA", "naturaliza", "reescreve isso", "melhora a escrita", "faz soar como pessoa", "revisão de roteiro", "humanizar copy", mesmo que o usuário não cite IA explicitamente. Dispara também quando o texto colado tem sinais óbvios de geração por IA (estrutura rígida, palavras corporativas, regra de três excessiva, parágrafos simétricos).
---

# Revisão Humanizada (Roteirista Humano)

Transforma textos com "cara de IA" em textos que soam escritos por uma pessoa real — naturais, com ritmo, com personalidade, e que funcionam quando lidos em voz alta.

## Princípio fundamental

O texto precisa passar no **teste da leitura em voz alta**. Se uma frase parece estranha, travada ou "formal demais" quando lida em voz alta, ela precisa ser reescrita. Escrita humana tem ritmo irregular, texturas, apartes, viradas e um pouco de bagunça controlada — não perfeição simétrica de relatório.

A revisão usa **prompt negativo**: não basta dizer "escreva melhor", é preciso BANIR ativamente padrões específicos que a IA produz por padrão.

---

## Fluxo de trabalho

Ao receber um texto para revisar:

1. **Diagnóstico rápido** — identificar quais padrões de IA estão presentes (palavras banidas, estruturas travadas, ritmo monótono, etc). Não precisa listar exaustivamente, só mapear mentalmente o que há para corrigir.
2. **Reescrita aplicando os bans** — reescrever o texto eliminando TODOS os padrões listados abaixo.
3. **Teste de leitura em voz alta (mental)** — reler cada frase perguntando: "Eu falaria isso numa conversa?". Se não, reescrever.
4. **Entrega em dois blocos**:
   - O texto revisado (sempre primeiro, limpo, pronto para uso)
   - Um breve resumo do que foi mudado (3–6 bullets, no máximo), apontando os padrões de IA removidos

Se o usuário pedir apenas a versão revisada sem explicação, entregue só o texto.

---

## Ban 1: Palavras proibidas (lista negra)

Essas palavras/expressões quase nunca aparecem em fala natural. A IA abusa delas porque foi treinada com texto corporativo e artigos mal escritos. Cortar ou substituir SEMPRE.

### Em português

**Transições e muletas genéricas:**
- "Além disso", "Ademais", "Outrossim", "Dito isso", "Nesse sentido", "Nesse contexto", "Vale ressaltar", "É importante destacar", "Em suma", "Por fim", "Em última análise", "De forma geral", "Fundamentalmente"
- "Vamos mergulhar", "Vamos explorar", "Bora lá" (quando forçado)
- "Aqui está um panorama", "Aqui está uma visão geral"

**Descritores formais vazios:**
- "Robusto", "Dinâmico", "Vibrante", "Rico", "Intrincado", "Multifacetado", "Holístico", "Abrangente", "Estratégico" (quando vazio), "Inovador" (quando vazio), "Sinérgico", "Alinhado", "Otimizado" (genérico)

**Frases de anúncio (nunca anuncie importância, mostre):**
- "É importante notar que...", "Vale destacar que...", "Isso ressalta...", "Isso evidencia...", "Isso demonstra que...", "Serve como...", "Marca um ponto de virada", "Representa um marco"

**Fechamentos vagos e feel-good:**
- "E é assim que você também pode alcançar o sucesso"
- "No final das contas, o que importa é..."
- "A jornada continua"
- "O céu é o limite"
- "As possibilidades são infinitas"

### Em inglês (se o texto for em inglês)

- Additionally, Furthermore, Moreover, In order to, Due to the fact, Both… and…, Here''s a breakdown, Let''s dive in
- Align, Enhance, Intricacies, Tapestry, Robust, Vibrant, Rich, Dynamic, Seamless
- Stands as, Serves as, Marks as a turning point, This highlights, This underscores

**Verbos genéricos** (substitua por ação concreta):
- "fazer" → quebrar, montar, puxar, empurrar, cortar (use o verbo específico)
- "realizar" → f','.skills\revisao-humanizada\SKILL.md','052f1b12149d406e4b390b4bcf5b9f0e0b3bed493af366529f25527b12bdc5ad','skill,simplicio,content',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:adversarial-ux-test','project_skill','skill://simplicio-runtime/adversarial-ux-test','skill: adversarial-ux-test','---
name: adversarial-ux-test
description: Roleplay the most difficult, tech-resistant user for your product. Browse the app as that persona, find every UX pain point, then filter complaints through a pragmatism layer to separate real problems from noise. Creates actionable tickets from genuine issues only.
version: 1.0.0
author: Omni @ Comelse
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qa, ux, testing, adversarial, dogfood, personas, user-testing]
    related_skills: [dogfood]
---

# Adversarial UX Test

Roleplay the worst-case user for your product — the person who hates technology, doesn''t want your software, and will find every reason to complain. Then filter their feedback through a pragmatism layer to separate real UX problems from "I hate computers" noise.

Think of it as an automated "mom test" — but angry.

## Why This Works

Most QA finds bugs. This finds **friction**. A technically correct app can still be unusable for real humans. The adversarial persona catches:
- Confusing terminology that makes sense to developers but not users
- Too many steps to accomplish basic tasks
- Missing onboarding or "aha moments"
- Accessibility issues (font size, contrast, click targets)
- Cold-start problems (empty states, no demo content)
- Paywall/signup friction that kills conversion

The **pragmatism filter** (Phase 3) is what makes this useful instead of just entertaining. Without it, you''d add a "print this page" button to every screen because Grandpa can''t figure out PDFs.

## How to Use

Tell the agent:
```
"Run an adversarial UX test on [URL]"
"Be a grumpy [persona type] and test [app name]"
"Do an asshole user test on my staging site"
```

You can provide a persona or let the agent generate one based on your product''s target audience.

## Step 1: Define the Persona

If no persona is provided, generate one by answering:

1. **Who is the HARDEST user for this product?** (age 50+, non-technical role, decades of experience doing it "the old way")
2. **What is their tech comfort level?** (the lower the better — WhatsApp-only, paper notebooks, wife set up their email)
3. **What is the ONE thing they need to accomplish?** (their core job, not your feature list)
4. **What would make them give up?** (too many clicks, jargon, slow, confusing)
5. **How do they talk when frustrated?** (blunt, sweary, dismissive, sighing)

### Good Persona Example
> **"Big Mick" McAllister** — 58-year-old S&C coach. Uses WhatsApp and that''s it. His "spreadsheet" is a paper notebook. "If I can''t figure it out in 10 seconds I''m going back to my notebook." Needs to log session results for 25 players. Hates small text, jargon, and passwords.

### Bad Persona Example
> "A user who doesn''t like the app" — too vague, no constraints, no voice.

The persona must be **specific enough to stay in character** for 20 minutes of testing.

## Step 2: Become the Asshole (Browse as the Persona)

1. Read any available project docs for app context and URLs
2. **Fully inhabit the persona** — their frustrations, limitations, goals
3. Navigate to the app using browser tools
4. **Attempt the persona''s ACTUAL TASKS** (not a feature tour):
   - Can they do what they came to do?
   - How many clicks/screens to accomplish it?
   - What confuses them?
   - What makes them angry?
   - Where do they get lost?
   - What would make them give up and go back to their old way?

5. Test these friction categories:
   - **First impression** — would they even bother past the landing page?
   - **Core workflow** — the ONE thing they need to do most often
   - **Error recovery** — what happens when they do something wrong?
   - **Readability** — text size, contrast, information density
   - **Speed** — does it feel faster than their current method?
   - **Terminology** — any jargon they wouldn''t understand?
   - **Navigation** — can they find their way back? do they know where they are?

6. Take screenshots of every pain point
7. Check browser console for JS errors on every page

## Step 3: The Rant (Write Feedback in Character)

Write the feedback AS ','.simplicio-loop\skills\dogfood\adversarial-ux-test\SKILL.md','6df3f38b974bb3370f82b1758158576cb37c3fa19197ee1b31aeca38d03705a6','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:google_meet:plugins','project_skill','skill://simplicio-runtime/google_meet','skill: google_meet','---
name: google_meet
description: Join a Google Meet call, transcribe live captions, optionally speak in realtime, and do the followup work afterwards. Use when the user asks the agent to sit in on a meeting, take notes, summarize, respond in-call, or action items from it.
version: 0.2.0
platforms:
  - linux
  - macos
metadata:
  hermes:
    tags: [meetings, google-meet, transcription, realtime-voice]
---

# google_meet

## When to use

The user says any of:

- "join my Meet at <url>"
- "take notes on this meeting"
- "summarize the meeting and send followups"
- "sit in on my standup"
- "be a bot in this call and speak up when X"

## Two modes

| Mode | What the bot does |
|---|---|
| `transcribe` (default) | Joins, enables captions, scrapes a transcript. Listen-only. |
| `realtime` | Same as transcribe PLUS speaks into the meeting via OpenAI Realtime. The agent calls `meet_say(text)` and the bot''s voice comes out of the call. |

Pick `realtime` only when the user actually wants the agent to speak. It costs real money (OpenAI Realtime is pay-per-audio-minute) and requires a virtual audio device set up on the machine running the bot.

## Two locations

| Location | When |
|---|---|
| Local (default) | Gateway machine runs the Playwright bot directly. |
| Remote node (`node="<name>"`) | Bot runs on a different machine that has a signed-in Chrome and (for realtime) a configured audio bridge. Useful when the gateway runs on a headless Linux box but the user''s real signed-in Chrome lives on their Mac. |

## Prerequisites the user must handle once

Easiest path — run the built-in installer:

```bash
hermes plugins enable google_meet
hermes meet install                 # pip deps + Chromium (transcribe only)
hermes meet install --realtime      # + pulseaudio-utils / brew blackhole+ffmpeg
hermes meet auth                    # optional; skips guest-lobby wait
hermes meet setup                   # preflight checks
```

`hermes meet install --realtime` prompts before running `sudo apt-get` (Linux)
or `brew install` (macOS). Pass `--yes` to skip the prompt. It will NOT touch
your macOS default-input setting — you have to select BlackHole 2ch in
System Settings yourself before starting a realtime meeting.

Or do it manually:
```bash
pip install playwright websockets && python -m playwright install chromium

# For realtime mode, additionally:
#   Linux:  sudo apt install pulseaudio-utils
#   macOS:  brew install blackhole-2ch ffmpeg
#           → System Settings → Sound → Input → BlackHole 2ch
#   Then set OPENAI_API_KEY or HERMES_MEET_REALTIME_KEY in ~/.hermes/.env
```

For a remote node:
```bash
# on the user''s Mac (where Chrome is signed in):
pip install playwright websockets && python -m playwright install chromium
hermes plugins enable google_meet
hermes meet node run --display-name my-mac    # persistent server
# copy the printed token

# on the gateway:
hermes meet node approve my-mac ws://<mac-ip>:18789 <token>
hermes meet node ping my-mac                   # confirm reachable
```

Run `hermes meet setup` to preflight local prereqs.

## Flow

1. **Join** — call `meet_join(url=..., mode=..., node=...)`. Returns immediately.
2. **Announce yourself** — no auto-consent. Say (in whatever channel the user is watching): "A Hermes agent bot is in this call taking notes."
3. **Poll** — `meet_status()` for liveness, `meet_transcript(last=20)` for recent captions. Don''t re-read the whole transcript every turn.
4. **Speak (realtime only)** — `meet_say(text="...")` queues text for TTS. The speech lags by ~2s. Don''t spam it.
5. **Leave** — `meet_leave()` when done, or set `duration="30m"` on `meet_join` for auto-leave.
6. **Follow up** — read `meet_transcript()` in full, summarize, and use regular tools to send the recap, file issues, schedule followups.

## Tool reference

| Tool | Parameters | Use |
|---|---|---|
| `meet_join` | `url`, `mode?`, `guest_name?`, `duration?`, `headed?`, `node?` | Start bot |
| `meet_status` | `node?` | Liveness + progress |
| `meet_transcript` | `last?`, `node?` | Read captions |
| `meet_leave` | `node?` | Cl','plugins\google_meet\SKILL.md','2547e8461ba201c7ab380d40b795e8723d7fb0d7b5a794bfec79eea6f0ed9cae','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:skill:simplicio','project_skill','skill://simplicio-runtime/skill','skill: skill','---
name: simplicio
description: SEMPRE ATIVO em qualquer tarefa de código, repositório ou execução. Antes de explorar use `simplicio runtime map`; antes de re-derivar use `simplicio memory`; para mudança mecânica decidida use `simplicio edit` (zero token). Reporta a economia de tokens medida pelo runtime.
---

# Simplicio — camada obrigatória (igual ao caveman: sempre ativa)

Esta skill está **sempre ativa**. Toda tarefa técnica passa pelo runtime `simplicio`
antes de gastar tokens do Claude. Não é recomendação — é o fluxo padrão.

## Loop (toda tarefa)

1. **Orientar** — `simplicio runtime map --repo . --for-llm markdown` antes de ler
   arquivos crus. Mapa comprimido em vez de despejar o repositório no modelo.
2. **Recordar** — `simplicio memory "<consulta>" --repo . --json` antes de
   re-derivar qualquer fato já conhecido.
3. **Editar mecanicamente** — mudança já decidida vai por
   `simplicio edit ''{"file":"...","operations":[...]}''` (zero token de escrita),
   nunca escrita manual do arquivo pelo modelo.
4. **Gerar só o não-decidido** — quando precisa do modelo, local-first
   (64 → 100 → 200 → 600 agentes); o modelo pago é o último degrau.
5. **Gate + evidência** — `simplicio gate classify` antes de mutar;
   `simplicio deliver` depois; trilha no HBP.

## Regra

- Em repositório com `simplicio` instalado, usar o runtime para mapear/editar/
  validar/gerar economiza tokens do modelo pago.

Net: **o modelo decide/revisa · o Simplicio mapeia, recorda, edita
determinístico, gateia e prova** — e a conta de tokens cai.
','publish\simpleti\simplicio\skill\SKILL.md','bca9c384843efb465b3c1308b14b6a89ca441351b331399e4754fe6a12815bd5','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:_template:skills','project_skill','skill://simplicio-runtime/_template','skill: _template','---
name: nome-da-skill
description: descreva em uma frase quando o agente deve ativar essa skill
---

# Skill: `nome-da-skill`

Template base para criar uma nova skill. Copie este arquivo para `.skills/<sua-skill>/SKILL.md` e edite cada section.

> **Como usar este template:** substitua o frontmatter, preencha as 4 sections obrigatórias (Trigger, Steps, Padrões, Definition of Done) e remova este bloco de instruções. Veja `.skills/README.md` para boas práticas.

---

## Trigger

> Liste **quando** essa skill deve ativar. Pense em palavras-chave que apareceriam no pedido do usuário ou na descrição da task. O agente faz match implícito pelo `description` do frontmatter, mas listar triggers explícitos aqui ajuda quando alguém revisa o catálogo de skills.

- Quando o usuário pedir "<exemplo de pedido típico>".
- Ao executar a tarefa "<nome da tarefa>".
- Sempre que tocar arquivos sob `<path/relevante>`.

---

## Steps

> Sequência **numerada** de passos que o agente segue. Cada passo deve ser um verbo no imperativo ("crie", "rode", "valide"). Evite passos compostos — se o passo tem dois verbos, divida em dois passos.

1. Identifique o contexto: leia o arquivo X / verifique a configuração Y.
2. Execute a ação principal: descreva exatamente o que mudar ou criar.
3. Valide o resultado: rode o comando de verificação adequado.
4. Documente o que foi feito: atualize changelog / comentário no PR / etc.

---

## Padrões

> Convenções específicas que o agente precisa respeitar. Naming, estrutura, tom, dependências evitadas. Use bullets curtos. Se virar lista grande (>10 itens), provavelmente esse conteúdo merece estar em `.specs/architecture/PATTERNS.md` em vez de uma skill.

- Naming: `<convenção>` (ex.: `kebab-case` para arquivos).
- Estrutura: `<padrão de pastas>` (ex.: `tests/e2e/<feature>.spec.ts`).
- Evite: `<antipadrão comum>` (ex.: `sleep` arbitrário, mock pra fazer passar).
- Prefira: `<padrão alternativo>` (ex.: `await expect(...).toBeVisible()`).

---

## Definition of Done

> Checklist **verificável** que o agente marca antes de declarar a tarefa concluída. Cada item precisa ser objetivamente checável (true/false), não subjetivo.

- [ ] Comando de validação roda sem erro localmente.
- [ ] Evidência gerada (screenshot / log / artifact) salva no caminho esperado.
- [ ] Documentação relacionada atualizada (se aplicável).
- [ ] Convenção de naming aplicada.
- [ ] Sem warnings novos no output do build.

---

## Exemplo (opcional)

> Inclua um exemplo concreto se a skill envolve gerar código ou comando. Use code block com tag de linguagem.

```bash
# Exemplo de comando que essa skill executaria
echo "substituir por exemplo real"
```

---

## Notas

> Espaço livre para gotchas, links pra docs externas, ADRs relacionadas, ou histórico breve. Mantenha curto.

- Link pra ADR relacionada: `.specs/architecture/ADR-XXX.md`.
- Doc externa: `<url>`.
- Última revisão: `<YYYY-MM-DD>`.
','skills\_template\SKILL.md','449fc6a7bcbec3836b0e0201fb1381e5d9e27be46cc0eae153f855d207d1a6bd','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:apple-notes:apple','project_skill','skill://simplicio-runtime/apple-notes','skill: apple-notes','---
name: apple-notes
description: "Manage Apple Notes via memo CLI: create, search, edit."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [Notes, Apple, macOS, note-taking]
    related_skills: [obsidian]
prerequisites:
  commands: [memo]
---

# Apple Notes

Use `memo` to manage Apple Notes directly from the terminal. Notes sync across all Apple devices via iCloud.

## Prerequisites

- **macOS** with Notes.app
- Install: `brew tap antoniorodr/memo && brew install antoniorodr/memo/memo`
- Grant Automation access to Notes.app when prompted (System Settings → Privacy → Automation)

## When to Use

- User asks to create, view, or search Apple Notes
- Saving information to Notes.app for cross-device access
- Organizing notes into folders
- Exporting notes to Markdown/HTML

## When NOT to Use

- Obsidian vault management → use the `obsidian` skill
- Bear Notes → separate app (not supported here)
- Quick agent-only notes → use the `memory` tool instead

## Quick Reference

### View Notes

```bash
memo notes                        # List all notes
memo notes -f "Folder Name"       # Filter by folder
memo notes -s "query"             # Search notes (fuzzy)
```

### Create Notes

```bash
memo notes -a                     # Interactive editor
memo notes -a "Note Title"        # Quick add with title
```

### Edit Notes

```bash
memo notes -e                     # Interactive selection to edit
```

### Delete Notes

```bash
memo notes -d                     # Interactive selection to delete
```

### Move Notes

```bash
memo notes -m                     # Move note to folder (interactive)
```

### Export Notes

```bash
memo notes -ex                    # Export to HTML/Markdown
```

## Limitations

- Cannot edit notes containing images or attachments
- Interactive prompts require terminal access (use pty=true if needed)
- macOS only — requires Apple Notes.app

## Rules

1. Prefer Apple Notes when user wants cross-device sync (iPhone/iPad/Mac)
2. Use the `memory` tool for agent-internal notes that don''t need to sync
3. Use the `obsidian` skill for Markdown-native knowledge management
','skills\apple\apple-notes\SKILL.md','c652e01e47938b8ac21c97873e0a14f5f3a773b554bd10737fbfdcc5e5c28d23','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:apple-reminders:apple','project_skill','skill://simplicio-runtime/apple-reminders','skill: apple-reminders','---
name: apple-reminders
description: "Apple Reminders via remindctl: add, list, complete."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [Reminders, tasks, todo, macOS, Apple]
prerequisites:
  commands: [remindctl]
---

# Apple Reminders

Use `remindctl` to manage Apple Reminders directly from the terminal. Tasks sync across all Apple devices via iCloud.

## Prerequisites

- **macOS** with Reminders.app
- Install: `brew install steipete/tap/remindctl`
- Grant Reminders permission when prompted
- Check: `remindctl status` / Request: `remindctl authorize`

## When to Use

- User mentions "reminder" or "Reminders app"
- Creating personal to-dos with due dates that sync to iOS
- Managing Apple Reminders lists
- User wants tasks to appear on their iPhone/iPad

## When NOT to Use

- Scheduling agent alerts → use the cronjob tool instead
- Calendar events → use Apple Calendar or Google Calendar
- Project task management → use GitHub Issues, Notion, etc.
- If user says "remind me" but means an agent alert → clarify first

## Quick Reference

### View Reminders

```bash
remindctl                    # Today''s reminders
remindctl today              # Today
remindctl tomorrow           # Tomorrow
remindctl week               # This week
remindctl overdue            # Past due
remindctl all                # Everything
remindctl 2026-01-04         # Specific date
```

### Manage Lists

```bash
remindctl list               # List all lists
remindctl list Work          # Show specific list
remindctl list Projects --create    # Create list
remindctl list Work --delete        # Delete list
```

### Create Reminders

```bash
remindctl add "Buy milk"
remindctl add --title "Call mom" --list Personal --due tomorrow
remindctl add --title "Meeting prep" --due "2026-02-15 09:00"
```

### Due Time vs Alarm / Early Nudge

`--due` and `--alarm` are different fields:

- `--due` sets the reminder''s due date/time.
- `--alarm` sets the EventKit alarm/notification trigger. Timed due reminders may default to an alarm at the due time, but pass `--alarm` explicitly when the user asks for an earlier nudge.

For a reminder due at 2:00 PM with a notification 30 minutes earlier:

```bash
remindctl add --title "Hairdresser" --due "2026-05-15 14:00" --alarm "2026-05-15 13:30"
```

To edit an existing reminder:

```bash
remindctl edit 87354 --due "2026-05-15 14:00" --alarm "2026-05-15 13:30"
```

The Reminders UI may show or group the item by the alarm time because that is when the notification fires. Verify with JSON instead of assuming the due time moved:

```bash
remindctl today --json
```

Expected shape:

- `dueDate`: actual due time
- `alarmDate`: notification / early nudge time

Apple''s public `EKReminder` docs list only reminder-specific properties. Alarm support comes from inherited `EKCalendarItem` behavior exposed by remindctl''s `--alarm` flag.

### Complete / Delete

```bash
remindctl complete 1 2 3          # Complete by ID
remindctl delete 4A83 --force     # Delete by ID
```

### Output Formats

```bash
remindctl today --json       # JSON for scripting
remindctl today --plain      # TSV format
remindctl today --quiet      # Counts only
```

## Date Formats

Accepted by `--due` and date filters:
- `today`, `tomorrow`, `yesterday`
- `YYYY-MM-DD`
- `YYYY-MM-DD HH:mm`
- ISO 8601 (`2026-01-04T12:34:56Z`)

## Rules

1. When user says "remind me", clarify: Apple Reminders (syncs to phone) vs agent cronjob alert
2. Always confirm reminder content and due date before creating
3. Use `--json` for programmatic parsing
','skills\apple\apple-reminders\SKILL.md','ee5084f2d7ec196488bef2c74248fb3d8328d1b2e3277ddda3f0de9da6fc7131','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:findmy:apple','project_skill','skill://simplicio-runtime/findmy','skill: findmy','---
name: findmy
description: "Track Apple devices/AirTags via FindMy.app on macOS."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [FindMy, AirTag, location, tracking, macOS, Apple]
---

# Find My (Apple)

Track Apple devices and AirTags via the FindMy.app on macOS. Since Apple doesn''t
provide a CLI for FindMy, this skill uses AppleScript to open the app and
screen capture to read device locations.

## Prerequisites

- **macOS** with Find My app and iCloud signed in
- Devices/AirTags already registered in Find My
- Screen Recording permission for terminal (System Settings → Privacy → Screen Recording)
- **Optional but recommended**: Install `peekaboo` for better UI automation:
  `brew install steipete/tap/peekaboo`

## When to Use

- User asks "where is my [device/cat/keys/bag]?"
- Tracking AirTag locations
- Checking device locations (iPhone, iPad, Mac, AirPods)
- Monitoring pet or item movement over time (AirTag patrol routes)

## Method 1: AppleScript + Screenshot (Basic)

### Open FindMy and Navigate

```bash
# Open Find My app
osascript -e ''tell application "FindMy" to activate''

# Wait for it to load
sleep 3

# Take a screenshot of the Find My window
screencapture -w -o /tmp/findmy.png
```

Then use `vision_analyze` to read the screenshot:
```
vision_analyze(image_url="/tmp/findmy.png", question="What devices/items are shown and what are their locations?")
```

### Switch Between Tabs

```bash
# Switch to Devices tab
osascript -e ''
tell application "System Events"
    tell process "FindMy"
        click button "Devices" of toolbar 1 of window 1
    end tell
end tell''

# Switch to Items tab (AirTags)
osascript -e ''
tell application "System Events"
    tell process "FindMy"
        click button "Items" of toolbar 1 of window 1
    end tell
end tell''
```

## Method 2: Peekaboo UI Automation (Recommended)

If `peekaboo` is installed, use it for more reliable UI interaction:

```bash
# Open Find My
osascript -e ''tell application "FindMy" to activate''
sleep 3

# Capture and annotate the UI
peekaboo see --app "FindMy" --annotate --path /tmp/findmy-ui.png

# Click on a specific device/item by element ID
peekaboo click --on B3 --app "FindMy"

# Capture the detail view
peekaboo image --app "FindMy" --path /tmp/findmy-detail.png
```

Then analyze with vision:
```
vision_analyze(image_url="/tmp/findmy-detail.png", question="What is the location shown for this device/item? Include address and coordinates if visible.")
```

## Workflow: Track AirTag Location Over Time

For monitoring an AirTag (e.g., tracking a cat''s patrol route):

```bash
# 1. Open FindMy to Items tab
osascript -e ''tell application "FindMy" to activate''
sleep 3

# 2. Click on the AirTag item (stay on page — AirTag only updates when page is open)

# 3. Periodically capture location
while true; do
    screencapture -w -o /tmp/findmy-$(date +%H%M%S).png
    sleep 300  # Every 5 minutes
done
```

Analyze each screenshot with vision to extract coordinates, then compile a route.

## Limitations

- FindMy has **no CLI or API** — must use UI automation
- AirTags only update location while the FindMy page is actively displayed
- Location accuracy depends on nearby Apple devices in the FindMy network
- Screen Recording permission required for screenshots
- AppleScript UI automation may break across macOS versions

## Rules

1. Keep FindMy app in the foreground when tracking AirTags (updates stop when minimized)
2. Use `vision_analyze` to read screenshot content — don''t try to parse pixels
3. For ongoing tracking, use a cronjob to periodically capture and log locations
4. Respect privacy — only track devices/items the user owns
','skills\apple\findmy\SKILL.md','19ec56e3b7f9f0be13c26d99948ed5684d8fb1f9c478da078c19356b5df63f57','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:imessage:apple','project_skill','skill://simplicio-runtime/imessage','skill: imessage','---
name: imessage
description: Send and receive iMessages/SMS via the imsg CLI on macOS.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [iMessage, SMS, messaging, macOS, Apple]
prerequisites:
  commands: [imsg]
---

# iMessage

Use `imsg` to read and send iMessage/SMS via macOS Messages.app.

## Prerequisites

- **macOS** with Messages.app signed in
- Install: `brew install steipete/tap/imsg`
- Grant Full Disk Access for terminal (System Settings → Privacy → Full Disk Access)
- Grant Automation permission for Messages.app when prompted

## When to Use

- User asks to send an iMessage or text message
- Reading iMessage conversation history
- Checking recent Messages.app chats
- Sending to phone numbers or Apple IDs

## When NOT to Use

- Telegram/Discord/Slack/WhatsApp messages → use the appropriate gateway channel
- Group chat management (adding/removing members) → not supported
- Bulk/mass messaging → always confirm with user first

## Quick Reference

### List Chats

```bash
imsg chats --limit 10 --json
```

### View History

```bash
# By chat ID
imsg history --chat-id 1 --limit 20 --json

# With attachments info
imsg history --chat-id 1 --limit 20 --attachments --json
```

### Send Messages

```bash
# Text only
imsg send --to "+14155551212" --text "Hello!"

# With attachment
imsg send --to "+14155551212" --text "Check this out" --file /path/to/image.jpg

# Force iMessage or SMS
imsg send --to "+14155551212" --text "Hi" --service imessage
imsg send --to "+14155551212" --text "Hi" --service sms
```

### Watch for New Messages

```bash
imsg watch --chat-id 1 --attachments
```

## Service Options

- `--service imessage` — Force iMessage (requires recipient has iMessage)
- `--service sms` — Force SMS (green bubble)
- `--service auto` — Let Messages.app decide (default)

## Rules

1. **Always confirm recipient and message content** before sending
2. **Never send to unknown numbers** without explicit user approval
3. **Verify file paths** exist before attaching
4. **Don''t spam** — rate-limit yourself

## Example Workflow

User: "Text mom that I''ll be late"

```bash
# 1. Find mom''s chat
imsg chats --limit 20 --json | jq ''.[] | select(.displayName | contains("Mom"))''

# 2. Confirm with user: "Found Mom at +1555123456. Send ''I''ll be late'' via iMessage?"

# 3. Send after confirmation
imsg send --to "+1555123456" --text "I''ll be late"
```
','skills\apple\imessage\SKILL.md','bc68b1648e301409bc25b1084ec26766213ca9f3c1b2fd3d3d6ebe3dbde9e967','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:macos-computer-use:apple','project_skill','skill://simplicio-runtime/macos-computer-use','skill: macos-computer-use','---
name: macos-computer-use
description: |
  Drive the macOS desktop in the background — screenshots, mouse, keyboard,
  scroll, drag — without stealing the user''s cursor, keyboard focus, or
  Space. Works with any tool-capable model. Load this skill whenever the
  `computer_use` tool is available.
version: 1.0.0
platforms: [macos]
metadata:
  hermes:
    tags: [computer-use, macos, desktop, automation, gui]
    category: desktop
    related_skills: [browser]
---

# macOS Computer Use (universal, any-model)

You have a `computer_use` tool that drives the Mac in the **background**.
Your actions do NOT move the user''s cursor, steal keyboard focus, or switch
Spaces. The user can keep typing in their editor while you click around in
Safari in another Space. This is the opposite of pyautogui-style automation.

Everything here works with any tool-capable model — Claude, GPT, Gemini, or
an open model running through a local OpenAI-compatible endpoint. There is
no Anthropic-native schema to learn.

## The canonical workflow

**Step 1 — Capture first.** Almost every task starts with:

```
computer_use(action="capture", mode="som", app="Safari")
```

Returns a screenshot with numbered overlays on every interactable element
AND an AX-tree index like:

```
#1  AXButton ''Back'' @ (12, 80, 28, 28) [Safari]
#2  AXTextField ''Address and Search'' @ (80, 80, 900, 32) [Safari]
#7  AXLink ''Sign In'' @ (900, 420, 80, 24) [Safari]
...
```

**Step 2 — Click by element index.** This is the single most important
habit:

```
computer_use(action="click", element=7)
```

Much more reliable than pixel coordinates for every model. Claude was
trained on both; other models are often only reliable with indices.

**Step 3 — Verify.** After any state-changing action, re-capture. You can
save a round-trip by asking for the post-action capture inline:

```
computer_use(action="click", element=7, capture_after=True)
```

## Capture modes

| `mode` | Returns | Best for |
|---|---|---|
| `som` (default) | Screenshot + numbered overlays + AX index | Vision models; preferred default |
| `vision` | Plain screenshot | When SOM overlay interferes with what you want to verify |
| `ax` | AX tree only, no image | Text-only models, or when you don''t need to see pixels |

## Actions

```
capture           mode=som|vision|ax   app=…  (default: current app)
click             element=N     OR     coordinate=[x, y]
double_click      element=N     OR     coordinate=[x, y]
right_click       element=N     OR     coordinate=[x, y]
middle_click      element=N     OR     coordinate=[x, y]
drag              from_element=N, to_element=M        (or from/to_coordinate)
scroll            direction=up|down|left|right   amount=3 (ticks)
type              text="…"
key               keys="cmd+s" | "return" | "escape" | "ctrl+alt+t"
wait              seconds=0.5
list_apps
focus_app         app="Safari"  raise_window=false   (default: don''t raise)
```

All actions accept optional `capture_after=True` to get a follow-up
screenshot in the same tool call.

All actions that target an element accept `modifiers=["cmd","shift"]` for
held keys.

## Background rules (the whole point)

1. **Never `raise_window=True`** unless the user explicitly asked you to
   bring a window to front. Input routing works without raising.
2. **Scope captures to an app** (`app="Safari"`) — less noisy, fewer
   elements, doesn''t leak other windows the user has open.
3. **Don''t switch Spaces.** cua-driver drives elements on any Space
   regardless of which one is visible.

## Text input patterns

- `type` sends whatever string you give it, respecting the current layout.
  Unicode works.
- For shortcuts use `key` with `+`-joined names:
  - `cmd+s` save
  - `cmd+t` new tab
  - `cmd+w` close tab
  - `return` / `escape` / `tab` / `space`
  - `cmd+shift+g` go to path (Finder)
  - Arrow keys: `up`, `down`, `left`, `right`, optionally with modifiers.

## Drag & drop

Prefer element indices:

```
computer_use(action="drag", from_element=3, to_element=17)
```

For a rubber-band selection on empty canvas, use coordinates:

```
compu','skills\apple\macos-computer-use\SKILL.md','13495469953451eebf320fe78a488a21f88f798fc0a548fa808b8517a31493df','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:asolaria-patterns','project_skill','skill://simplicio-runtime/asolaria-patterns','skill: asolaria-patterns','---
name: asolaria-patterns
description: Port dos padrões Asolaria (JesseBrown1980) para o Simplicio Runtime como primitivas determinísticas testáveis — N-Nest cosign/corrective gate, HRM two-level planner, BEHCS-256 supervisor federado.
---

# Asolaria Patterns — Port Determinístico

Use este skill quando evoluir o `simplicio-runtime` absorvendo padrões do
ecossistema Asolaria (N-Nest-Prime, HRM, BEHCS-256). Todo padrão aqui é uma
**primitiva determinística testável**, nunca um stub LLM.

Princípio do `simplicio-runtime-asolaria-porting`: prefira transform puro,
gate explícito, persistência tipada. O runtime é o *determinism kernel*; estes
padrões são bibliotecas Python/Rust puras que o `simplicio-agent` consome.

## Padrões portados

### 1) N-Nest — Cosign + Corrective Gate (`lib/nest_cosign.py`)
Port de `N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED/nest-depth3-verify.cjs`.
- Cada nó = agente PID + watcher PID (2 PIDs) que recomputa a ground-truth.
- Gate corretivo: pai autoriza filho só se `reported == watcher_recomputed_truth`.
- Roll-up de *consent*: só dispara se TODOS os níveis passam.
- Tamper test: injeta confabulação em folha 3 níveis fundo; gate TEM que pegar.
- Aproveita `ReceiptChain` (hash-chained) do `simplicio-fabric` para cosign.

### 2) HRM — Two-Level Planner (`lib/hierarchical_planner.py`)
Port de `HRM/models/hrm/hrm_act_v1.py` (loop H/L sem torch).
- High-level (LENTO): re-planeja a cada `H_cycles` passos.
- Low-level (RÁPIDO): executa `L_cycles` micro-passos entre re-planejos.
- Carry state: `z_H` / `z_L` propagados (aqui: dicts/strings determinísticos).

### 3) BEHCS-256 — Supervisor Federado (`lib/behcs_supervisor.py`)
Port de `asolaria-behcs-256/tools/behcs/behcs-agent-operator.js`.
- Cube/register NDJSON com GC bounded (truncate em MAX).
- Hilbert address = sha256_16 (compat `asolaria_hbi_hbp::agt`).
- Loop de operador: screenshot→check→corrige→verify→GC, max loops.

## Uso
```bash
python3 skills/asolaria-patterns/lib/nest_cosign.py --selftest
python3 skills/asolaria-patterns/lib/hierarchical_planner.py --selftest
python3 skills/asolaria-patterns/lib/behcs_supervisor.py --selftest
python3 -m pytest skills/asolaria-patterns/tests/ -q
```

## Verificação (obrigatória)
Cada padrão tem `--selftest` e teste pytest que PROVA o comportamento:
- `nest_cosign`: run limpo → apex VERIFIED; run com tamper → apex UNVERIFIED + path nomeado.
- `hierarchical_planner`: H re-planeja N vezes, L executa L_cycles cada.
- `behcs_supervisor`: register estoura MAX → truncate p/ últimas MAX linhas.

## Pitfalls
- Não substitua gate por stub. O gate deve *morder* (tamper test obrigatório).
- Não use torch/LLM no core — estes são primitivas puras.
- Mantenha compat de hashing com `asolaria_hbi_hbp` (sha256_16 = `AGT-`+16hex).
','skills\asolaria\asolaria-patterns\SKILL.md','708e72e2a672f8b86856c39bdba368c9199f7c3865586fe5e787b783f1821e79','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:antigravity-cli:autonomous-ai-agents','project_skill','skill://simplicio-runtime/antigravity-cli','skill: antigravity-cli','---
name: antigravity-cli
description: "Operate the Antigravity CLI (agy): plugins, auth, sandbox."
version: 0.1.0
author: Tony Simons (asimons81), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, Antigravity, CLI, Auth, Plugins, Sandbox]
    related_skills: [grok, codex, claude-code, hermes-agent]
---

# Antigravity CLI (`agy`)

Operator guide for the Antigravity CLI, invoked as `agy`. Run all `agy`
commands through the Hermes `terminal` tool; inspect its config and logs with
`read_file`. This skill is reference + procedure — it does not wrap a network
API, so there is nothing to authenticate from Hermes itself.

## When to Use

- Installing, updating, or smoke-testing the `agy` binary
- Driving non-interactive `agy --print` / `agy -p` one-shots
- Debugging Antigravity auth, sandbox, permissions, or plugin state
- Reading Antigravity settings, keybindings, conversations, or logs

## Mental model

Antigravity has two layers — keep them distinct or the guidance will be wrong:

1. **Shell wrapper commands** — `agy help`, `agy install`, `agy plugin`,
   `agy update`, `agy changelog`. Run these through the `terminal` tool.
2. **Interactive in-session slash commands** — `/config`, `/permissions`,
   `/skills`, `/agents`, etc. These only exist inside a running `agy` TUI
   session, not on the shell wrapper.

`agy help` shows the shell wrapper surface, NOT the in-session slash commands.

## Prerequisites

- The `agy` binary on PATH. Verify through the `terminal` tool:
  `command -v agy && agy --version`.
- No env vars or API keys required by this skill — Antigravity manages its own
  auth via the OS keyring / browser sign-in (see Authentication below).

## How to Run

Invoke every `agy` command through the `terminal` tool. Examples:

```
terminal(command="agy --version")
terminal(command="agy help")
terminal(command="agy plugin list")
terminal(command="agy --print ''Summarize the repo in 3 bullets''", workdir="/path/to/project")
```

For an interactive multi-turn TUI session, launch `agy` with `pty=true` (and
tmux for capture/monitoring), the same pattern the `codex` / `claude-code`
skills use. For one-shot smoke tests and scripted prompts, prefer
`agy --print` (non-interactive).

To inspect Antigravity''s own files, use `read_file` on the paths under Core
paths below — do not `cat` them through the terminal.

## Core paths

- Binary / entrypoint: `agy`
- App data dir: `~/.gemini/antigravity-cli/`
- Settings file: `~/.gemini/antigravity-cli/settings.json`
- Keybindings file: `~/.gemini/antigravity-cli/keybindings.json`
- Logs: `~/.gemini/antigravity-cli/log/cli-*.log`
- Conversations: `~/.gemini/antigravity-cli/conversations/`
- Brain artifacts: `~/.gemini/antigravity-cli/brain/`
- History: `~/.gemini/antigravity-cli/history.jsonl`
- Plugin staging: `~/.gemini/antigravity-cli/plugins/<plugin_name>/`

## Quick Reference

### Wrapper commands
- `agy changelog`
- `agy help`
- `agy install`
- `agy plugin` / `agy plugins`
- `agy update`

### Useful flags
- `--add-dir`
- `--continue` / `-c`
- `--conversation`
- `--dangerously-skip-permissions`
- `--print` / `-p`
- `--print-timeout`
- `--prompt`
- `--prompt-interactive` / `-i`
- `--sandbox`
- `--log-file`
- `--version`

### Plugin subcommands (`agy plugin --help`)
- `list`, `import [source]`, `install <target>`, `uninstall <name>`,
  `enable <name>`, `disable <name>`, `validate [path]`, `link <mp> <target>`,
  `help`

### Install flags (`agy install --help`)
- `--dir`, `--skip-aliases`, `--skip-path`

### In-session slash commands
- **Conversation control:** `/resume` (`/switch`), `/rewind` (`/undo`),
  `/rename <name>`, `/clear`, `/fork`, `/reset`, `/new`
- **Settings & tools:** `/config`, `/settings`, `/permissions`, `/model`,
  `/keybindings`, `/statusline`, `/tasks`, `/skills`, `/mcp`, `/open <path>`,
  `/usage`, `/logout`, `/agents`
- **Prompt helpers:** `@` path autocomplete, `esc esc` clears the prompt (when
  not streaming), `!` runs a terminal command directly, `?` opens help

## Settings and permissions

### Common settin','skills\autonomous-ai-agents\antigravity-cli\SKILL.md','f7f0f73be1240e70ed7c0e7960037fea05347f033e1babb572c1d7fcc8ed2d70','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:blackbox:autonomous-ai-agents','project_skill','skill://simplicio-runtime/blackbox','skill: blackbox','---
name: blackbox
description: Delegate coding tasks to Blackbox AI CLI agent. Multi-model agent with built-in judge that runs tasks through multiple LLMs and picks the best result. Requires the blackbox CLI and a Blackbox AI API key.
version: 1.0.0
author: Hermes Agent (Nous Research)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, Blackbox, Multi-Agent, Judge, Multi-Model]
    related_skills: [claude-code, codex, hermes-agent]
---

# Blackbox CLI

Delegate coding tasks to [Blackbox AI](https://www.blackbox.ai/) via the Hermes terminal. Blackbox is a multi-model coding agent CLI that dispatches tasks to multiple LLMs (Claude, Codex, Gemini, Blackbox Pro) and uses a judge to select the best implementation.

The CLI is [open-source](https://github.com/blackboxaicode/cli) (GPL-3.0, TypeScript, forked from Gemini CLI) and supports interactive sessions, non-interactive one-shots, checkpointing, MCP, and vision model switching.

## Prerequisites

- Node.js 20+ installed
- Blackbox CLI installed: `npm install -g @blackboxai/cli`
- Or install from source:
  ```
  git clone https://github.com/blackboxaicode/cli.git
  cd cli && npm install && npm install -g .
  ```
- API key from [app.blackbox.ai/dashboard](https://app.blackbox.ai/dashboard)
- Configured: run `blackbox configure` and enter your API key
- Use `pty=true` in terminal calls — Blackbox CLI is an interactive terminal app

## One-Shot Tasks

```
terminal(command="blackbox --prompt ''Add JWT authentication with refresh tokens to the Express API''", workdir="/path/to/project", pty=true)
```

For quick scratch work:
```
terminal(command="cd $(mktemp -d) && git init && blackbox --prompt ''Build a REST API for todos with SQLite''", pty=true)
```

## Background Mode (Long Tasks)

For tasks that take minutes, use background mode so you can monitor progress:

```
# Start in background with PTY
terminal(command="blackbox --prompt ''Refactor the auth module to use OAuth 2.0''", workdir="~/project", background=true, pty=true)
# Returns session_id

# Monitor progress
process(action="poll", session_id="<id>")
process(action="log", session_id="<id>")

# Send input if Blackbox asks a question
process(action="submit", session_id="<id>", data="yes")

# Kill if needed
process(action="kill", session_id="<id>")
```

## Checkpoints & Resume

Blackbox CLI has built-in checkpoint support for pausing and resuming tasks:

```
# After a task completes, Blackbox shows a checkpoint tag
# Resume with a follow-up task:
terminal(command="blackbox --resume-checkpoint ''task-abc123-2026-03-06'' --prompt ''Now add rate limiting to the endpoints''", workdir="~/project", pty=true)
```

## Session Commands

During an interactive session, use these commands:

| Command | Effect |
|---------|--------|
| `/compress` | Shrink conversation history to save tokens |
| `/clear` | Wipe history and start fresh |
| `/stats` | View current token usage |
| `Ctrl+C` | Cancel current operation |

## PR Reviews

Clone to a temp directory to avoid modifying the working tree:

```
terminal(command="REVIEW=$(mktemp -d) && git clone https://github.com/user/repo.git $REVIEW && cd $REVIEW && gh pr checkout 42 && blackbox --prompt ''Review this PR against main. Check for bugs, security issues, and code quality.''", pty=true)
```

## Parallel Work

Spawn multiple Blackbox instances for independent tasks:

```
terminal(command="blackbox --prompt ''Fix the login bug''", workdir="/tmp/issue-1", background=true, pty=true)
terminal(command="blackbox --prompt ''Add unit tests for auth''", workdir="/tmp/issue-2", background=true, pty=true)

# Monitor all
process(action="list")
```

## Multi-Model Mode

Blackbox''s unique feature is running the same task through multiple models and judging the results. Configure which models to use via `blackbox configure` — select multiple providers to enable the Chairman/judge workflow where the CLI evaluates outputs from different models and picks the best one.

## Key Flags

| Flag | Effect |
|------|--------|
| `--prompt "task"` | Non-interactive one-shot execution |
| `','skills\autonomous-ai-agents\blackbox\SKILL.md','350cce5dab1524a79d64e7402da89fdad00116c1dbca0df4d39d8b5288342989','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:claude-code:autonomous-ai-agents','project_skill','skill://simplicio-runtime/claude-code','skill: claude-code','---
name: claude-code
description: "Delegate coding to Claude Code CLI (features, PRs)."
version: 2.2.0
author: Hermes Agent + Teknium
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, Claude, Anthropic, Code-Review, Refactoring, PTY, Automation]
    related_skills: [codex, hermes-agent, opencode]
---

# Claude Code — Hermes Orchestration Guide

Delegate coding tasks to [Claude Code](https://code.claude.com/docs/en/cli-reference) (Anthropic''s autonomous coding agent CLI) via the Hermes terminal. Claude Code v2.x can read files, write code, run shell commands, spawn subagents, and manage git workflows autonomously.

## Prerequisites

- **Install:** `npm install -g @anthropic-ai/claude-code`
- **Auth:** run `claude` once to log in (browser OAuth for Pro/Max, or set `ANTHROPIC_API_KEY`)
- **Console auth:** `claude auth login --console` for API key billing
- **SSO auth:** `claude auth login --sso` for Enterprise
- **Check status:** `claude auth status` (JSON) or `claude auth status --text` (human-readable)
- **Health check:** `claude doctor` — checks auto-updater and installation health
- **Version check:** `claude --version` (requires v2.x+)
- **Update:** `claude update` or `claude upgrade`

## Two Orchestration Modes

Hermes interacts with Claude Code in two fundamentally different ways. Choose based on the task.

### Mode 1: Print Mode (`-p`) — Non-Interactive (PREFERRED for most tasks)

Print mode runs a one-shot task, returns the result, and exits. No PTY needed. No interactive prompts. This is the cleanest integration path.

```
terminal(command="claude -p ''Add error handling to all API calls in src/'' --allowedTools ''Read,Edit'' --max-turns 10", workdir="/path/to/project", timeout=120)
```

**When to use print mode:**
- One-shot coding tasks (fix a bug, add a feature, refactor)
- CI/CD automation and scripting
- Structured data extraction with `--json-schema`
- Piped input processing (`cat file | claude -p "analyze this"`)
- Any task where you don''t need multi-turn conversation

**Print mode skips ALL interactive dialogs** — no workspace trust prompt, no permission confirmations. This makes it ideal for automation.

### Mode 2: Interactive PTY via tmux — Multi-Turn Sessions

Interactive mode gives you a full conversational REPL where you can send follow-up prompts, use slash commands, and watch Claude work in real time. **Requires tmux orchestration.**

```
# Start a tmux session
terminal(command="tmux new-session -d -s claude-work -x 140 -y 40")

# Launch Claude Code inside it
terminal(command="tmux send-keys -t claude-work ''cd /path/to/project && claude'' Enter")

# Wait for startup, then send your task
# (after ~3-5 seconds for the welcome screen)
terminal(command="sleep 5 && tmux send-keys -t claude-work ''Refactor the auth module to use JWT tokens'' Enter")

# Monitor progress by capturing the pane
terminal(command="sleep 15 && tmux capture-pane -t claude-work -p -S -50")

# Send follow-up tasks
terminal(command="tmux send-keys -t claude-work ''Now add unit tests for the new JWT code'' Enter")

# Exit when done
terminal(command="tmux send-keys -t claude-work ''/exit'' Enter")
```

**When to use interactive mode:**
- Multi-turn iterative work (refactor → review → fix → test cycle)
- Tasks requiring human-in-the-loop decisions
- Exploratory coding sessions
- When you need to use Claude''s slash commands (`/compact`, `/review`, `/model`)

## PTY Dialog Handling (CRITICAL for Interactive Mode)

Claude Code presents up to two confirmation dialogs on first launch. You MUST handle these via tmux send-keys:

### Dialog 1: Workspace Trust (first visit to a directory)
```
❯ 1. Yes, I trust this folder    ← DEFAULT (just press Enter)
  2. No, exit
```
**Handling:** `tmux send-keys -t <session> Enter` — default selection is correct.

### Dialog 2: Bypass Permissions Warning (only with --dangerously-skip-permissions)
```
❯ 1. No, exit                    ← DEFAULT (WRONG choice!)
  2. Yes, I accept
```
**Handling:** Must navigate DOWN first, then Enter:
```
tmux send-keys -t <session> Down && s','skills\autonomous-ai-agents\claude-code\SKILL.md','be029fae449fae3966348dc547750c96401a1368057b97d02684f1ffe44c9e90','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:codex:autonomous-ai-agents','project_skill','skill://simplicio-runtime/codex','skill: codex','---
name: codex
description: "Delegate coding to OpenAI Codex CLI (features, PRs)."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, Codex, OpenAI, Code-Review, Refactoring]
    related_skills: [claude-code, hermes-agent]
---

# Codex CLI

Delegate coding tasks to [Codex](https://github.com/openai/codex) via the Hermes terminal. Codex is OpenAI''s autonomous coding agent CLI.

## When to use

- Building features
- Refactoring
- PR reviews
- Batch issue fixing

Requires the codex CLI and a git repository.

## Prerequisites

- Codex installed: `npm install -g @openai/codex`
- OpenAI auth configured: either `OPENAI_API_KEY` or Codex OAuth credentials
  from the Codex CLI login flow
- **Must run inside a git repository** — Codex refuses to run outside one
- Use `pty=true` in terminal calls — Codex is an interactive terminal app

For Hermes itself, `model.provider: openai-codex` uses Hermes-managed Codex
OAuth from `~/.hermes/auth.json` after `hermes auth add openai-codex`. For the
standalone Codex CLI, a valid CLI OAuth session may live under
`~/.codex/auth.json`; do not treat a missing `OPENAI_API_KEY` alone as proof
that Codex auth is missing.

## One-Shot Tasks

```
terminal(command="codex exec ''Add dark mode toggle to settings''", workdir="~/project", pty=true)
```

For scratch work (Codex needs a git repo):
```
terminal(command="cd $(mktemp -d) && git init && codex exec ''Build a snake game in Python''", pty=true)
```

## Background Mode (Long Tasks)

```
# Start in background with PTY
terminal(command="codex exec --full-auto ''Refactor the auth module''", workdir="~/project", background=true, pty=true)
# Returns session_id

# Monitor progress
process(action="poll", session_id="<id>")
process(action="log", session_id="<id>")

# Send input if Codex asks a question
process(action="submit", session_id="<id>", data="yes")

# Kill if needed
process(action="kill", session_id="<id>")
```

## Key Flags

| Flag | Effect |
|------|--------|
| `exec "prompt"` | One-shot execution, exits when done |
| `--full-auto` | Sandboxed but auto-approves file changes in workspace |
| `--yolo` | No sandbox, no approvals (fastest, most dangerous) |
| `--sandbox danger-full-access` | No Codex sandbox; useful when the host service context breaks bubblewrap |

## Hermes Gateway Caveat

When invoking the Codex CLI from a Hermes gateway/service context (for example,
Telegram-driven agent sessions), Codex `workspace-write` sandboxing may fail even
when the same command works in the user''s interactive shell. A typical symptom is
bubblewrap/user-namespace errors such as `setting up uid map: Permission denied`
or `loopback: Failed RTM_NEWADDR: Operation not permitted`.

In that context, prefer:

```
codex exec --sandbox danger-full-access "<task>"
```

Use process boundaries as the safety layer instead: explicit `workdir`, clean git
status before launch, narrow task prompts, `git diff` review, targeted tests, and
human/agent confirmation before committing broad changes.

## PR Reviews

Clone to a temp directory for safe review:

```
terminal(command="REVIEW=$(mktemp -d) && git clone https://github.com/user/repo.git $REVIEW && cd $REVIEW && gh pr checkout 42 && codex review --base origin/main", pty=true)
```

## Parallel Issue Fixing with Worktrees

```
# Create worktrees
terminal(command="git worktree add -b fix/issue-78 /tmp/issue-78 main", workdir="~/project")
terminal(command="git worktree add -b fix/issue-99 /tmp/issue-99 main", workdir="~/project")

# Launch Codex in each
terminal(command="codex --yolo exec ''Fix issue #78: <description>. Commit when done.''", workdir="/tmp/issue-78", background=true, pty=true)
terminal(command="codex --yolo exec ''Fix issue #99: <description>. Commit when done.''", workdir="/tmp/issue-99", background=true, pty=true)

# Monitor
process(action="list")

# After completion, push and create PRs
terminal(command="cd /tmp/issue-78 && git push -u origin fix/issue-78")
terminal(command="gh pr create --repo user/repo --head fix/issue-78 --title ''fix: ...','skills\autonomous-ai-agents\codex\SKILL.md','489b60f50127f7d852d547e9ad33035c683c0b3f2e826b807ba8e3487fc05e7d','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:grok:autonomous-ai-agents','project_skill','skill://simplicio-runtime/grok','skill: grok','---
name: grok
description: "Delegate coding to xAI Grok Build CLI (features, PRs)."
version: 0.1.0
author: Matt Maximo (MattMaximo), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, Grok, xAI, Code-Review, Refactoring, Automation]
    related_skills: [codex, claude-code, hermes-agent]
---

# Grok Build CLI — Hermes Orchestration Guide

Delegate coding tasks to [Grok Build](https://docs.x.ai/build/overview) (xAI''s
autonomous coding agent CLI, the `grok` command) via the Hermes terminal. Grok
can read files, write code, run shell commands, spawn subagents, and manage git
workflows. It runs three ways: an interactive TUI, **headless** (`-p`), and as
an **ACP agent** over JSON-RPC.

This is the third sibling to `codex` and `claude-code`. The orchestration
pattern is nearly identical — **prefer headless `-p` for one-shots**, use a PTY
for interactive sessions.

## When to use

- Building features
- Refactoring
- PR reviews
- Batch issue fixing
- Any task where you''d otherwise reach for Codex / Claude Code but want Grok

## Prerequisites

- **Install (preferred):** `npm install -g @xai-official/grok`
  - The official installer `curl -fsSL https://x.ai/cli/install.sh | bash` also
    works, but the `x.ai` host is Cloudflare-walled in some environments. The
    npm path avoids that dependency entirely.
- **Auth — SuperGrok / X Premium+ subscription (primary path):**
  - Run `grok login` once → opens a browser for OAuth → token cached in
    `~/.grok/auth.json`. This uses your **SuperGrok or X Premium+** subscription
    (no per-token API billing).
  - Check sign-in state by looking for `~/.grok/auth.json`, or run a cheap
    headless smoke test: `grok --no-auto-update -p "Say ok."`
  - In the TUI, `/logout` signs out and `/login` (or relaunching) signs back in.
- **No git repo required** — unlike Codex, Grok runs fine outside a git
  directory (good for scratch/throwaway tasks).
- **Claude Code / AGENTS.md compatible with zero config** — Grok auto-reads
  `CLAUDE.md`, `.claude/` (skills, agents, MCPs, hooks, rules), and the
  `AGENTS.md` family. Existing project context just works.

> **API-key fallback (not the default for this user):** Grok also supports
> setting the `XAI_API_KEY` environment variable for pay-as-you-go billing
> via `api.x.ai`. Only use
> this if `grok login` / SuperGrok auth is unavailable. The subscription path
> (`grok login`) is the intended setup here.

## Two Orchestration Modes

### Mode 1: Headless (`-p`) — Non-Interactive (PREFERRED)

Runs a one-shot task, prints the result, and exits. No PTY, no interactive
dialogs to navigate. This is the cleanest integration path — the analog of
`claude -p` and `codex exec`.

```
terminal(command="grok --no-auto-update -p ''Add a dark mode toggle to settings''", workdir="/path/to/project", timeout=180)
```

Always pass `--no-auto-update` in automation to skip background update checks.

**When to use headless:**
- One-shot coding tasks (fix a bug, add a feature, refactor)
- CI/CD automation and scripting
- Structured output parsing with `--output-format json`
- Any task that doesn''t need multi-turn conversation

### Mode 2: Interactive PTY — Multi-Turn TUI Sessions

The TUI is a fullscreen, mouse-interactive app. Drive it with `pty=true`. For
robust monitoring/input use tmux (same pattern as the `claude-code` skill).

```
# Launch in a tmux session for capture-pane monitoring
terminal(command="tmux new-session -d -s grok-work -x 140 -y 40")
terminal(command="tmux send-keys -t grok-work ''cd /path/to/project && grok'' Enter")

# Wait for startup, then send a task
terminal(command="sleep 5 && tmux send-keys -t grok-work ''Refactor the auth module to use JWT'' Enter")

# Monitor progress
terminal(command="sleep 15 && tmux capture-pane -t grok-work -p -S -50")

# Exit when done
terminal(command="tmux send-keys -t grok-work ''/quit'' Enter && sleep 1 && tmux kill-session -t grok-work")
```

**Tip for headless-but-inline output:** if you want TUI-style output without the
fullscreen alt-screen takeover (e.g. for cleaner lo','skills\autonomous-ai-agents\grok\SKILL.md','5ec202a3315374547fa1ed081c48ba6a4d84b6cd7b507f848be7d65442c725c9','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:hermes-agent:autonomous-ai-agents','project_skill','skill://simplicio-runtime/hermes-agent','skill: hermes-agent','---
name: hermes-agent
description: "Configure, extend, or contribute to Hermes Agent."
version: 2.1.0
author: Hermes Agent + Teknium
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [hermes, setup, configuration, multi-agent, spawning, cli, gateway, development]
    homepage: https://github.com/NousResearch/hermes-agent
    related_skills: [claude-code, codex, opencode]
---

# Hermes Agent

Hermes Agent is an open-source AI agent framework by Nous Research that runs in your terminal, messaging platforms, and IDEs. It belongs to the same category as Claude Code (Anthropic), Codex (OpenAI), and OpenClaw — autonomous coding and task-execution agents that use tool calling to interact with your system. Hermes works with any LLM provider (OpenRouter, Anthropic, OpenAI, DeepSeek, local models, and 15+ others) and runs on Linux, macOS, and WSL.

What makes Hermes different:

- **Self-improving through skills** — Hermes learns from experience by saving reusable procedures as skills. When it solves a complex problem, discovers a workflow, or gets corrected, it can persist that knowledge as a skill document that loads into future sessions. Skills accumulate over time, making the agent better at your specific tasks and environment.
- **Persistent memory across sessions** — remembers who you are, your preferences, environment details, and lessons learned. Pluggable memory backends (built-in, Honcho, Mem0, and more) let you choose how memory works.
- **Multi-platform gateway** — the same agent runs on Telegram, Discord, Slack, WhatsApp, Signal, Matrix, Email, and 10+ other platforms with full tool access, not just chat.
- **Provider-agnostic** — swap models and providers mid-workflow without changing anything else. Credential pools rotate across multiple API keys automatically.
- **Profiles** — run multiple independent Hermes instances with isolated configs, sessions, skills, and memory.
- **Extensible** — plugins, MCP servers, custom tools, webhook triggers, cron scheduling, and the full Python ecosystem.

People use Hermes for software development, research, system administration, data analysis, content creation, home automation, and anything else that benefits from an AI agent with persistent context and full system access.

**This skill helps you work with Hermes Agent effectively** — setting it up, configuring features, spawning additional agent instances, troubleshooting issues, finding the right commands and settings, and understanding how the system works when you need to extend or contribute to it.

**Docs:** https://hermes-agent.nousresearch.com/docs/

## Quick Start

```bash
# Install
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

# Interactive chat (default)
hermes

# Single query
hermes chat -q "What is the capital of France?"

# Setup wizard
hermes setup

# Change model/provider
hermes model

# Check health
hermes doctor
```

---

## CLI Reference

### Global Flags

```
hermes [flags] [command]

  --version, -V             Show version
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --pass-session-id         Include session ID in system prompt
```

No subcommand defaults to `chat`.

### Chat

```
hermes chat [flags]
  -q, --query TEXT          Single query, non-interactive
  -m, --model MODEL         Model (e.g. anthropic/claude-sonnet-4)
  -t, --toolsets LIST       Comma-separated toolsets
  --provider PROVIDER       Force provider (openrouter, anthropic, nous, etc.)
  -v, --verbose             Verbose output
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --source TAG              Session source tag (default: cli)
```

### Configuration

```
hermes setup ','skills\autonomous-ai-agents\hermes-agent\SKILL.md','05145b53affd5f7d62f36c873220c45d1c3d9ed132e3db4a1073139409d7d227','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:honcho:autonomous-ai-agents','project_skill','skill://simplicio-runtime/honcho','skill: honcho','---
name: honcho
description: Configure and use Honcho memory with Hermes -- cross-session user modeling, multi-profile peer isolation, observation config, dialectic reasoning, session summaries, and context budget enforcement. Use when setting up Honcho, troubleshooting memory, managing profiles with Honcho peers, or tuning observation, recall, and dialectic settings.
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Honcho, Memory, Profiles, Observation, Dialectic, User-Modeling, Session-Summary]
    homepage: https://docs.honcho.dev
    related_skills: [hermes-agent]
prerequisites:
  pip: [honcho-ai]
---

# Honcho Memory for Hermes

Honcho provides AI-native cross-session user modeling. It learns who the user is across conversations and gives every Hermes profile its own peer identity while sharing a unified view of the user.

## When to Use

- Setting up Honcho (cloud or self-hosted)
- Troubleshooting memory not working / peers not syncing
- Creating multi-profile setups where each agent has its own Honcho peer
- Tuning observation, recall, dialectic depth, or write frequency settings
- Understanding what the 5 Honcho tools do and when to use them
- Configuring context budgets and session summary injection

## Setup

### Cloud (app.honcho.dev)

```bash
hermes memory setup honcho
# select "cloud", paste API key from https://app.honcho.dev
```

### Self-hosted

```bash
hermes memory setup honcho
# select "local", enter base URL (e.g. http://localhost:8000)
```

See: https://docs.honcho.dev/v3/guides/integrations/hermes#running-honcho-locally-with-hermes

### Verify

```bash
hermes honcho status    # shows resolved config, connection test, peer info
```

## Architecture

### Base Context Injection

When Honcho injects context into the system prompt (in `hybrid` or `context` recall modes), it assembles the base context block in this order:

1. **Session summary** -- a short digest of the current session so far (placed first so the model has immediate conversational continuity)
2. **User representation** -- Honcho''s accumulated model of the user (preferences, facts, patterns)
3. **AI peer card** -- the identity card for this Hermes profile''s AI peer

The session summary is generated automatically by Honcho at the start of each turn (when a prior session exists). It gives the model a warm start without replaying full history.

### Cold / Warm Prompt Selection

Honcho automatically selects between two prompt strategies:

| Condition | Strategy | What happens |
|-----------|----------|--------------|
| No prior session or empty representation | **Cold start** | Lightweight intro prompt; skips summary injection; encourages the model to learn about the user |
| Existing representation and/or session history | **Warm start** | Full base context injection (summary → representation → card); richer system prompt |

You do not need to configure this -- it is automatic based on session state.

### Peers

Honcho models conversations as interactions between **peers**. Hermes creates two peers per session:

- **User peer** (`peerName`): represents the human. Honcho builds a user representation from observed messages.
- **AI peer** (`aiPeer`): represents this Hermes instance. Each profile gets its own AI peer so agents develop independent views.

### Observation

Each peer has two observation toggles that control what Honcho learns from:

| Toggle | What it does |
|--------|-------------|
| `observeMe` | Peer''s own messages are observed (builds self-representation) |
| `observeOthers` | Other peers'' messages are observed (builds cross-peer understanding) |

Default: all four toggles **on** (full bidirectional observation).

Configure per-peer in `honcho.json`:

```json
{
  "observation": {
    "user": { "observeMe": true, "observeOthers": true },
    "ai":   { "observeMe": true, "observeOthers": true }
  }
}
```

Or use the shorthand presets:

| Preset | User | AI | Use case |
|--------|------|----|----------|
| `"directional"` (default) | me:on, others:on | me:on, others:','skills\autonomous-ai-agents\honcho\SKILL.md','170d69331e733c8f9786f661b98656e568dabfe9108dd8cc904287c8c01619fe','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:opencode:autonomous-ai-agents','project_skill','skill://simplicio-runtime/opencode','skill: opencode','---
name: opencode
description: "Delegate coding to OpenCode CLI (features, PR review)."
version: 1.2.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, OpenCode, Autonomous, Refactoring, Code-Review]
    related_skills: [claude-code, codex, hermes-agent]
---

# OpenCode CLI

Use [OpenCode](https://opencode.ai) as an autonomous coding worker orchestrated by Hermes terminal/process tools. OpenCode is a provider-agnostic, open-source AI coding agent with a TUI and CLI.

## When to Use

- User explicitly asks to use OpenCode
- You want an external coding agent to implement/refactor/review code
- You need long-running coding sessions with progress checks
- You want parallel task execution in isolated workdirs/worktrees

## Prerequisites

- OpenCode installed: `npm i -g opencode-ai@latest` or `brew install anomalyco/tap/opencode`
- Auth configured: `opencode auth login` or set provider env vars (OPENROUTER_API_KEY, etc.)
- Verify: `opencode auth list` should show at least one provider
- Git repository for code tasks (recommended)
- `pty=true` for interactive TUI sessions

## Binary Resolution (Important)

Shell environments may resolve different OpenCode binaries. If behavior differs between your terminal and Hermes, check:

```
terminal(command="which -a opencode")
terminal(command="opencode --version")
```

If needed, pin an explicit binary path:

```
terminal(command="$HOME/.opencode/bin/opencode run ''...''", workdir="~/project", pty=true)
```

## One-Shot Tasks

Use `opencode run` for bounded, non-interactive tasks:

```
terminal(command="opencode run ''Add retry logic to API calls and update tests''", workdir="~/project")
```

Attach context files with `-f`:

```
terminal(command="opencode run ''Review this config for security issues'' -f config.yaml -f .env.example", workdir="~/project")
```

Show model thinking with `--thinking`:

```
terminal(command="opencode run ''Debug why tests fail in CI'' --thinking", workdir="~/project")
```

Force a specific model:

```
terminal(command="opencode run ''Refactor auth module'' --model openrouter/anthropic/claude-sonnet-4", workdir="~/project")
```

## Interactive Sessions (Background)

For iterative work requiring multiple exchanges, start the TUI in background:

```
terminal(command="opencode", workdir="~/project", background=true, pty=true)
# Returns session_id

# Send a prompt
process(action="submit", session_id="<id>", data="Implement OAuth refresh flow and add tests")

# Monitor progress
process(action="poll", session_id="<id>")
process(action="log", session_id="<id>")

# Send follow-up input
process(action="submit", session_id="<id>", data="Now add error handling for token expiry")

# Exit cleanly — Ctrl+C
process(action="write", session_id="<id>", data="\x03")
# Or just kill the process
process(action="kill", session_id="<id>")
```

**Important:** Do NOT use `/exit` — it is not a valid OpenCode command and will open an agent selector dialog instead. Use Ctrl+C (`\x03`) or `process(action="kill")` to exit.

### TUI Keybindings

| Key | Action |
|-----|--------|
| `Enter` | Submit message (press twice if needed) |
| `Tab` | Switch between agents (build/plan) |
| `Ctrl+P` | Open command palette |
| `Ctrl+X L` | Switch session |
| `Ctrl+X M` | Switch model |
| `Ctrl+X N` | New session |
| `Ctrl+X E` | Open editor |
| `Ctrl+C` | Exit OpenCode |

### Resuming Sessions

After exiting, OpenCode prints a session ID. Resume with:

```
terminal(command="opencode -c", workdir="~/project", background=true, pty=true)  # Continue last session
terminal(command="opencode -s ses_abc123", workdir="~/project", background=true, pty=true)  # Specific session
```

## Common Flags

| Flag | Use |
|------|-----|
| `run ''prompt''` | One-shot execution and exit |
| `--continue` / `-c` | Continue the last OpenCode session |
| `--session <id>` / `-s` | Continue a specific session |
| `--agent <name>` | Choose OpenCode agent (build or plan) |
| `--model provider/model` | Force specific model |
| `--format json` | Machine-readable output/events |
|','skills\autonomous-ai-agents\opencode\SKILL.md','81c2044dad7f2ba989b7d97ef56ed32bbfea36060b1545cf8975da8f6c650e3f','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:openhands:autonomous-ai-agents','project_skill','skill://simplicio-runtime/openhands','skill: openhands','---
name: openhands
description: Delegate coding to OpenHands CLI (model-agnostic, LiteLLM).
version: 0.1.0
author: Tim Koepsel (xzessmedia), Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Coding-Agent, OpenHands, Model-Agnostic, LiteLLM]
    related_skills: [claude-code, codex, opencode, hermes-agent]
---

# OpenHands CLI

Delegate coding tasks to the [OpenHands CLI](https://github.com/All-Hands-AI/OpenHands) via the `terminal` tool. OpenHands is model-agnostic: any LiteLLM-supported provider (OpenAI, Anthropic, OpenRouter, DeepSeek, Ollama, vLLM, etc.).

This skill is the headless-mode wrapper for batch / one-shot delegation. The interactive textual UI is not used from Hermes.

## When to Use

- User wants a coding task delegated to OpenHands specifically.
- User wants a coding agent that can run on a non-Anthropic / non-OpenAI provider (DeepSeek, Qwen, Ollama, vLLM, Nous, etc.) — sibling skills `claude-code` and `codex` are tied to one vendor.
- Multi-step file edits + shell commands inside a workspace.

For Claude-native, prefer `claude-code`. For OpenAI-native, prefer `codex`. For Hermes-native subagents, use `delegate_task`.

## Prerequisites

1. Install upstream (requires Python 3.12+ and `uv`):

   ```
   terminal(command="uv tool install openhands --python 3.12")
   ```

   Verify: `openhands --version` (currently `OpenHands CLI 1.16.0` / `SDK v1.21.0` at time of writing).

2. Pick a model and set env vars for `--override-with-envs`:

   ```
   export LLM_MODEL=openrouter/openai/gpt-4o-mini       # or any LiteLLM slug
   export LLM_API_KEY=$OPENROUTER_API_KEY
   export LLM_BASE_URL=https://openrouter.ai/api/v1     # omit for native OpenAI
   ```

   `LLM_MODEL` uses LiteLLM''s full slug. When the provider is OpenRouter the slug is doubly-prefixed: `openrouter/<vendor>/<model>` (e.g. `openrouter/anthropic/claude-sonnet-4.5`). For native Anthropic: `anthropic/claude-sonnet-4-5`. For native OpenAI: `openai/gpt-4o-mini`.

3. Suppress the startup banner so JSON output isn''t preceded by ASCII art:

   ```
   export OPENHANDS_SUPPRESS_BANNER=1
   ```

## How to Run

Always invoke through the `terminal` tool. Always pass `--headless --json --override-with-envs --exit-without-confirmation` for automation.

### One-shot task

```
terminal(
  command="OPENHANDS_SUPPRESS_BANNER=1 LLM_MODEL=openrouter/openai/gpt-4o-mini LLM_API_KEY=$OPENROUTER_API_KEY LLM_BASE_URL=https://openrouter.ai/api/v1 openhands --headless --json --override-with-envs --exit-without-confirmation -t ''Add error handling to all API calls in src/''",
  workdir="/path/to/project",
  timeout=600
)
```

### Background for long tasks

```
terminal(command="<same as above>", workdir="/path/to/project", background=true, notify_on_complete=true)
process(action="poll", session_id="<id>")
process(action="log", session_id="<id>")
```

### Resume a previous conversation

OpenHands prints `Conversation ID: <32-hex>` and a `Hint: openhands --resume <dashed-uuid>` line at the end of each run. Use the dashed form to resume:

```
terminal(
  command="OPENHANDS_SUPPRESS_BANNER=1 LLM_MODEL=... openhands --headless --json --override-with-envs --exit-without-confirmation --resume <dashed-uuid> -t ''Now fix the bug you found''",
  workdir="/path/to/project"
)
```

## Real Flag List

Verified against `openhands --help` (CLI 1.16.0). Anything not in this table is not a flag — pass it via env var or settings file.

| Flag | Effect |
|------|--------|
| `--headless` | No UI, requires `-t` or `-f`. Auto-approves all actions (no `--llm-approve` in this mode). |
| `--json` | JSONL event stream (requires `--headless`). |
| `-t TEXT` | Task prompt. |
| `-f PATH` | Read task from file. |
| `--resume [ID]` | Resume conversation. No ID → list recent. |
| `--last` | Resume most recent (with `--resume`). |
| `--override-with-envs` | Apply `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` env vars. Without this, OpenHands uses `~/.openhands/settings.json` and ignores the env. |
| `--exit-without-confirmation` | Don''t show the "are you sure" exit dialog. |
| `--alwa','skills\autonomous-ai-agents\openhands\SKILL.md','5237552f955df8343c89f82548456ea50297d6fb5c6c50f7e7eafcdb2c5b0aaa','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:evm:blockchain','project_skill','skill://simplicio-runtime/evm','skill: evm','---
name: evm
description: "Read-only EVM client: wallets, tokens, gas across 8 chains."
version: 1.0.0
author: Mibayy (@Mibayy), youssefea (@youssefea), ethernet8023 (@ethernet8023), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [EVM, Ethereum, BNB, BSC, Base, Arbitrum, Polygon, Optimism, Avalanche, zkSync, Blockchain, Crypto, Web3, DeFi, NFT, ENS, Whale, Security]
    category: blockchain
    related_skills: [solana]
    requires_toolsets: [terminal]
---

# EVM Blockchain Skill

Query EVM-compatible blockchain data across 8 chains with USD pricing.
14 commands: wallet portfolio, token info, transactions, activity, gas tracker,
network stats, price lookup, multi-chain scan, whale detection, ENS resolution,
allowance checker, contract inspector, and transaction decoder.

Supports 8 chains: Ethereum, BNB Chain (BSC), Base, Arbitrum One, Polygon,
Optimism, Avalanche (C-Chain), zkSync Era.

No API key needed. Zero external dependencies — Python standard library only
(urllib, json, argparse, threading).

> **Supersedes the standalone `base` skill.** Base-specific tokens (AERO, DEGEN,
> TOSHI, BRETT, WELL, cbETH, cbBTC, wstETH, rETH) and all Base RPC functionality
> previously living under `optional-skills/blockchain/base/` have been folded
> into this skill. Pass `--chain base` to any command for Base coverage.

---

## When to Use
- User asks for a wallet balance or portfolio on any EVM chain
- User wants to check the same wallet across ALL chains at once
- User wants to inspect a transaction by hash (or decode what it did)
- User wants ERC-20 token metadata, price, supply, or market cap
- User wants recent transaction history for an address
- User wants current gas prices or to compare fees across chains
- User wants to find large whale transfers in recent blocks
- User asks to resolve an ENS name (vitalik.eth) or reverse-lookup an address
- User wants to check if a contract has dangerous token approvals
- User wants to inspect a smart contract (proxy? ERC-20? ERC-721? bytecode size?)
- User wants to compare gas costs across chains before a transaction

---

## Prerequisites
Python 3.8+ standard library only. No pip installs required.
Pricing: CoinGecko free API (rate-limited, ~10-30 req/min).
ENS: ensideas.com public API.
Tx decoding: 4byte.directory public API.

Override RPC endpoint: `export EVM_RPC_URL=https://your-rpc.com`

Helper script path: `~/.hermes/skills/blockchain/evm/scripts/evm_client.py`

---

## Quick Reference

```
SCRIPT=~/.hermes/skills/blockchain/evm/scripts/evm_client.py

# Network & prices
python3 $SCRIPT stats                            # Ethereum stats
python3 $SCRIPT stats --chain arbitrum           # Arbitrum stats
python3 $SCRIPT compare                          # Gas + prices ALL 8 chains

# Wallet
python3 $SCRIPT wallet 0xd8dA...96045            # Portfolio (ETH + ERC-20)
python3 $SCRIPT wallet 0xd8dA...96045 --chain bsc
python3 $SCRIPT multichain 0xd8dA...96045        # Same wallet on ALL chains

# Tokens & prices
python3 $SCRIPT price ETH
python3 $SCRIPT price 0xdAC1...1ec7              # By contract address
python3 $SCRIPT token 0xdAC1...1ec7              # ERC-20 metadata + market cap

# Transactions
python3 $SCRIPT tx 0x5c50...f060                 # Transaction details
python3 $SCRIPT decode 0x5c50...f060             # Decode input data (4byte.directory)
python3 $SCRIPT activity 0xd8dA...96045          # Recent transactions

# Gas
python3 $SCRIPT gas                              # Gas prices + cost estimates
python3 $SCRIPT gas --chain optimism

# Security
python3 $SCRIPT allowance 0xd8dA...96045         # Dangerous ERC-20 approvals
python3 $SCRIPT contract 0xdAC1...1ec7           # Contract inspection (proxy? standards?)

# ENS
python3 $SCRIPT ens vitalik.eth                  # Name -> address + profile
python3 $SCRIPT ens 0xd8dA...96045               # Address -> ENS name

# Whale detection
python3 $SCRIPT whale                            # Large transfers (last 20 blocks, >$10k)
python3 $SCRIPT whale --blocks 50 --min-usd 100000 --chain arbi','skills\blockchain\evm\SKILL.md','acbf4a2f1177b6c08df7bcfb087f80bbd139156193d4394276b3cbd4e578e2a6','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:hyperliquid:blockchain','project_skill','skill://simplicio-runtime/hyperliquid','skill: hyperliquid','---
name: hyperliquid
description: Hyperliquid market data, account history, trade review.
version: 0.1.0
author: Hugo Sequier (Hugo-SEQUIER), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Hyperliquid, Blockchain, Crypto, Trading, Perpetuals, Spot, DeFi]
    related_skills: []
---

# Hyperliquid Skill

Query Hyperliquid market and account data through the public `/info` endpoint.
Read-only — no API key, no signing, no order placement.

12 commands: `dexs`, `markets`, `spots`, `candles`, `funding`, `l2`, `state`,
`spot-balances`, `fills`, `orders`, `review`, `export`. Stdlib only
(`urllib`, `json`, `argparse`).

---

## When to Use

- User asks for Hyperliquid perp or spot market data, candles, funding, or L2 book
- User wants to inspect a wallet''s perp positions, spot balances, fills, or orders
- User wants a post-trade review combining recent fills with market context
- User wants to inspect builder-deployed perp dexs or HIP-3 markets
- User wants a normalized JSON export of candles + funding for backtesting prep

---

## Prerequisites

Stdlib only — no external packages, no API key.

The script reads `${HERMES_HOME:-~/.hermes}/.env` for two optional defaults:

- `HYPERLIQUID_API_URL` — defaults to `https://api.hyperliquid.xyz`. Set to
  `https://api.hyperliquid-testnet.xyz` for testnet.
- `HYPERLIQUID_USER_ADDRESS` — default address for `state`, `spot-balances`,
  `fills`, `orders`, and `review`. If unset, pass the address as the first
  positional argument.

A project `.env` in the current working directory is honored as a dev fallback.

Helper script: `~/.hermes/skills/blockchain/hyperliquid/scripts/hyperliquid_client.py`

---

## How to Run

Invoke through the `terminal` tool:

```bash
python3 ~/.hermes/skills/blockchain/hyperliquid/scripts/hyperliquid_client.py <command> [args]
```

Add `--json` to any command for machine-readable output.

---

## Quick Reference

```bash
hyperliquid_client.py dexs
hyperliquid_client.py markets [--dex DEX] [--limit N] [--sort volume|oi|funding_abs|change_abs|name]
hyperliquid_client.py spots [--limit N]
hyperliquid_client.py candles <coin> [--interval 1h] [--hours 24] [--limit N]
hyperliquid_client.py funding <coin> [--hours 72] [--limit N]
hyperliquid_client.py l2 <coin> [--levels N]
hyperliquid_client.py state [address] [--dex DEX]
hyperliquid_client.py spot-balances [address] [--limit N]
hyperliquid_client.py fills [address] [--hours N] [--limit N] [--aggregate-by-time]
hyperliquid_client.py orders [address] [--limit N]
hyperliquid_client.py review [address] [--coin COIN] [--hours N] [--fills N]
hyperliquid_client.py export <coin> [--interval 1h] [--hours N] [--output PATH]
```

For `state`, `spot-balances`, `fills`, `orders`, and `review`, the address is
optional when `HYPERLIQUID_USER_ADDRESS` is set in `${HERMES_HOME:-~/.hermes}/.env`.

---

## Procedure

### 1. Discover DEXs and Markets

```bash
python3 ~/.hermes/skills/blockchain/hyperliquid/scripts/hyperliquid_client.py dexs

python3 ~/.hermes/skills/blockchain/hyperliquid/scripts/hyperliquid_client.py \
  markets --limit 15 --sort volume

python3 ~/.hermes/skills/blockchain/hyperliquid/scripts/hyperliquid_client.py \
  spots --limit 15
```

- `--dex` only applies to perp endpoints; omit for the first perp dex.
- Spot pairs may show as `PURR/USDC` or aliases like `@107`.
- HIP-3 markets prefix the coin with the dex, e.g. `mydex:BTC`.

### 2. Pull Historical Market Data

```bash
python3 ~/.hermes/skills/blockchain/hyperliquid/scripts/hyperliquid_client.py \
  candles BTC --interval 1h --hours 72 --limit 48

python3 ~/.hermes/skills/blockchain/hyperliquid/scripts/hyperliquid_client.py \
  funding BTC --hours 168 --limit 30
```

Time-range endpoints paginate. For larger windows, repeat with a later
`startTime` or use `export` (below).

### 3. Inspect Live Order Book

```bash
python3 ~/.hermes/skills/blockchain/hyperliquid/scripts/hyperliquid_client.py \
  l2 BTC --levels 10
```

Use when asked about book depth, near-term liquidity, or potential market
impact of a large order.

###','skills\blockchain\hyperliquid\SKILL.md','22a990eafa5f89e6b6ad50a40b2b9b5215bc9ea9e5c047d23f0949d3fb1e74fe','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:solana:blockchain','project_skill','skill://simplicio-runtime/solana','skill: solana','---
name: solana
description: Query Solana blockchain data with USD pricing — wallet balances, token portfolios with values, transaction details, NFTs, whale detection, and live network stats. Uses Solana RPC + CoinGecko. No API key required.
version: 0.2.0
author: Deniz Alagoz (gizdusum), enhanced by Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Solana, Blockchain, Crypto, Web3, RPC, DeFi, NFT]
    related_skills: []
---

# Solana Blockchain Skill

Query Solana on-chain data enriched with USD pricing via CoinGecko.
8 commands: wallet portfolio, token info, transactions, activity, NFTs,
whale detection, network stats, and price lookup.

No API key needed. Uses only Python standard library (urllib, json, argparse).

---

## When to Use

- User asks for a Solana wallet balance, token holdings, or portfolio value
- User wants to inspect a specific transaction by signature
- User wants SPL token metadata, price, supply, or top holders
- User wants recent transaction history for an address
- User wants NFTs owned by a wallet
- User wants to find large SOL transfers (whale detection)
- User wants Solana network health, TPS, epoch, or SOL price
- User asks "what''s the price of BONK/JUP/SOL?"

---

## Prerequisites

The helper script uses only Python standard library (urllib, json, argparse).
No external packages required.

Pricing data comes from CoinGecko''s free API (no key needed, rate-limited
to ~10-30 requests/minute). For faster lookups, use `--no-prices` flag.

---

## Quick Reference

RPC endpoint (default): https://api.mainnet-beta.solana.com
Override: export SOLANA_RPC_URL=https://your-private-rpc.com

Helper script path: ~/.hermes/skills/blockchain/solana/scripts/solana_client.py

```
python3 solana_client.py wallet   <address> [--limit N] [--all] [--no-prices]
python3 solana_client.py tx       <signature>
python3 solana_client.py token    <mint_address>
python3 solana_client.py activity <address> [--limit N]
python3 solana_client.py nft      <address>
python3 solana_client.py whales   [--min-sol N]
python3 solana_client.py stats
python3 solana_client.py price    <mint_or_symbol>
```

---

## Procedure

### 0. Setup Check

```bash
python3 --version

# Optional: set a private RPC for better rate limits
export SOLANA_RPC_URL="https://api.mainnet-beta.solana.com"

# Confirm connectivity
python3 ~/.hermes/skills/blockchain/solana/scripts/solana_client.py stats
```

### 1. Wallet Portfolio

Get SOL balance, SPL token holdings with USD values, NFT count, and
portfolio total. Tokens sorted by value, dust filtered, known tokens
labeled by name (BONK, JUP, USDC, etc.).

```bash
python3 ~/.hermes/skills/blockchain/solana/scripts/solana_client.py \
  wallet 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM
```

Flags:
- `--limit N` — show top N tokens (default: 20)
- `--all` — show all tokens, no dust filter, no limit
- `--no-prices` — skip CoinGecko price lookups (faster, RPC-only)

Output includes: SOL balance + USD value, token list with prices sorted
by value, dust count, NFT summary, total portfolio value in USD.

### 2. Transaction Details

Inspect a full transaction by its base58 signature. Shows balance changes
in both SOL and USD.

```bash
python3 ~/.hermes/skills/blockchain/solana/scripts/solana_client.py \
  tx 5j7s8K...your_signature_here
```

Output: slot, timestamp, fee, status, balance changes (SOL + USD),
program invocations.

### 3. Token Info

Get SPL token metadata, current price, market cap, supply, decimals,
mint/freeze authorities, and top 5 holders.

```bash
python3 ~/.hermes/skills/blockchain/solana/scripts/solana_client.py \
  token DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263
```

Output: name, symbol, decimals, supply, price, market cap, top 5
holders with percentages.

### 4. Recent Activity

List recent transactions for an address (default: last 10, max: 25).

```bash
python3 ~/.hermes/skills/blockchain/solana/scripts/solana_client.py \
  activity 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM --limit 25
```

### 5. NFT Portfolio

List NFTs owned by a wallet (he','skills\blockchain\solana\SKILL.md','8036f0a7f2db7e19ac893e455c453d66291f6b43d8085144f6b88a3ee4954d8d','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:one-three-one-rule:communication','project_skill','skill://simplicio-runtime/one-three-one-rule','skill: one-three-one-rule','---
name: one-three-one-rule
description: >
  Structured decision-making framework for technical proposals and trade-off analysis.
  When the user faces a choice between multiple approaches (architecture decisions,
  tool selection, refactoring strategies, migration paths), this skill produces a
  1-3-1 format: one clear problem statement, three distinct options with pros/cons,
  and one concrete recommendation with definition of done and implementation plan.
  Use when the user asks for a "1-3-1", says "give me options", or needs help
  choosing between competing approaches.
platforms: [linux, macos, windows]
version: 1.0.0
author: Willard Moore
license: MIT
category: communication
metadata:
  hermes:
    tags: [communication, decision-making, proposals, trade-offs]
---

# 1-3-1 Communication Rule

Structured decision-making format for when a task has multiple viable approaches and the user needs a clear recommendation. Produces a concise problem framing, three options with trade-offs, and an actionable plan for the recommended path.

## When to Use

- The user explicitly asks for a "1-3-1" response.
- The user says "give me options" or "what are my choices" for a technical decision.
- A task has multiple viable approaches with meaningful trade-offs (architecture, tooling, migration strategy).
- The user needs a proposal they can forward to a team or stakeholder.

Do NOT use for simple questions with one obvious answer, debugging sessions, or tasks where the user has already decided on an approach.

## Procedure

1. **Problem** (one sentence)
   - State the core decision or desired outcome in a single concise sentence.
   - Focus on the *what*, not the *how* — no implementation details, tool names, or specific technologies.
   - Keep it tight. If you need "and", you''re describing two problems.

2. **Options** (exactly three)
   - Present three distinct, viable approaches labeled A, B, C.
   - Each option gets a brief description, pros, and cons.
   - Options should represent genuinely different strategies, not minor variations of the same approach.

3. **Recommendation** (one option)
   - State which option you recommend and why, based on the user''s context and priorities.
   - Be direct — this is your professional judgment, not a hedge.

4. **Definition of Done**
   - List the specific success criteria for the recommended option.
   - These are concrete, verifiable outcomes — not vague aspirations.
   - If the user picks a different option, revise this section to match.

5. **Implementation Plan**
   - Concrete steps to execute the recommended option.
   - Include specific commands, tools, or actions where applicable.
   - If the user picks a different option, revise this section to match.

## Verification

- Response has exactly one Problem sentence.
- Response has exactly three Options (A, B, C) with pros and cons for each.
- Response has a single Recommendation that picks one option with reasoning.
- Definition of Done and Implementation Plan align with the recommended option.
- If the user selects a different option, Recommendation, DoD, and Implementation Plan update accordingly.

## Example

User: "Give me a 1-3-1 for adding retry logic to our API client."

Agent:

**Problem:** API calls to external services fail intermittently under load and need graceful retry handling.

**Options:**

- **Option A: Exponential backoff with jitter in a shared utility.**
  Pros: Simple, well-understood pattern; single implementation shared across all callers.
  Cons: No circuit-breaking; callers still block during retries.

- **Option B: Retry library (tenacity) as a decorator on each endpoint call.**
  Pros: Configurable per-endpoint; built-in support for circuit breakers and rate limits.
  Cons: Adds a dependency; decorator pattern can obscure control flow.

- **Option C: Queue-based async retry with dead letter handling.**
  Pros: Non-blocking; failed calls are tracked and replayable; scales well.
  Cons: Significant complexity increase; requires a queue backend; overkill for low-volume services.

**Recommendation:** Option A.','skills\communication\one-three-one-rule\SKILL.md','b899ee001a1caca821ded6a9f6680d9c1ba9bb914667e99a50a96c5e2072db12','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:conventional-commits:skills','project_skill','skill://simplicio-runtime/conventional-commits','skill: conventional-commits','---
name: conventional-commits
description: padronizar mensagens de commit seguindo Conventional Commits (type, scope opcional, subject curto, breaking change marcado)
---

# Skill: `conventional-commits`

Toda mensagem de commit deste projeto segue o padrão **Conventional Commits**. Isso habilita changelog automático, version bump por SemVer e leitura rápida do histórico. Sem exceção.

---

## Trigger

- Toda vez que rodar `git commit`.
- Antes de abrir PR (verificar histórico do branch).
- Quando rebase/squash consolidar commits — a mensagem final também segue o padrão.
- Quando o usuário pedir "faz commit", "commita as mudanças", "abre PR".

---

## Padrão

```
<type>(<scope>)?: <subject>

[<body opcional>]

[<footer opcional>]
```

- **type** (obrigatório, minúsculo): `feat | fix | docs | style | refactor | perf | test | build | ci | chore | revert`.
- **scope** (opcional): área afetada em uma palavra (`auth`, `api`, `ui`, `deps`). Entre parênteses.
- **subject** (obrigatório): descrição curta no imperativo presente, minúsculo, sem ponto final, **máx 72 caracteres**.
- **body** (opcional): linhas explicando o "porquê", não o "o quê". Separado do subject por linha em branco. Wrap a 72 colunas.
- **footer** (opcional): referências a issue (`Closes #123`), co-autores, ou marcação de breaking change.

### Tipos — quando usar cada um

| Type | Quando |
| --- | --- |
| `feat` | Nova feature visível ao usuário |
| `fix` | Correção de bug |
| `docs` | Só documentação (README, JSDoc, comentários) |
| `style` | Formatação que não muda comportamento (espaços, ponto-e-vírgula) |
| `refactor` | Reestruturação sem mudar comportamento externo |
| `perf` | Melhoria de performance |
| `test` | Adicionar/atualizar testes |
| `build` | Sistema de build, dependências (`package.json`, `tsconfig`) |
| `ci` | Pipeline CI/CD (`.github/workflows`, scripts de deploy) |
| `chore` | Manutenção genérica que não cabe nas outras |
| `revert` | Reverte commit anterior (mensagem cita o SHA revertido) |

### Breaking change

Mudança incompatível com a versão anterior. **Duas formas válidas**, escolha uma:

1. **Bang após o type**: `feat!:`, `refactor!:`, `fix!:`.
2. **Footer explícito**: `BREAKING CHANGE: <descrição do impacto e migração>`.

Se possível, use as duas para deixar 100% claro.

---

## Exemplos

```text
feat(auth): add password reset flow via email link

fix(api): handle null user-agent header without crashing

docs: update README with new install steps

refactor(checkout): extract pricing logic into PriceCalculator

perf(search): debounce input to reduce API calls from 30 to 3 per typing burst

test(auth): cover expired-token edge case in login flow

build(deps): bump playwright to 1.45.0

ci: add Node 22 to test matrix

chore: remove unused dotenv import

revert: revert "feat(auth): add password reset flow via email link"

This reverts commit a1b2c3d4 — caused regression on existing reset tokens.
Closes #482

feat(api)!: rename /users endpoint to /accounts

BREAKING CHANGE: clients hitting /users must migrate to /accounts.
The old route returns 410 Gone. See migration guide in .specs/architecture/ADR-005.md.
```

---

## Steps

1. **Identifique o tipo** dominante da mudança. Se houve fix + refactor no mesmo diff, geralmente cabe `refactor` com nota no body sobre o fix incidental — ou separe em dois commits.
2. **Escolha o scope** (opcional) com base na pasta/módulo principal afetado. Mantenha consistência com scopes já usados no histórico.
3. **Escreva o subject** no imperativo: "add", "fix", "remove" — não "added", "fixes".
4. **Adicione body** se a motivação não for óbvia pelo subject. Explique o "porquê", referencie a task: `Refs #task-id`.
5. **Marque breaking change** quando aplicável (`!` no header e/ou `BREAKING CHANGE:` no footer).
6. **Verifique tamanho**: subject ≤ 72 chars, linhas do body ≤ 72.
7. **Commit**. Se o projeto usa `commitlint` no hook `commit-msg`, ele bloqueia mensagens fora do padrão — corrija e tente de novo.

---

## Definition of Done

- [ ] Mensagem segue `<type>(<scope>)?: <subject>` com type válido da lis','skills\conventional-commits\SKILL.md','dbc789f69ccf7da4c1d5b5fc794a998da613ae81075a3ede680888caa3a7a03e','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:architecture-diagram:creative','project_skill','skill://simplicio-runtime/architecture-diagram','skill: architecture-diagram','---
name: architecture-diagram
description: "Dark-themed SVG architecture/cloud/infra diagrams as HTML."
version: 1.0.0
author: Cocoon AI (hello@cocoon-ai.com), ported by Hermes Agent
license: MIT
dependencies: []
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [architecture, diagrams, SVG, HTML, visualization, infrastructure, cloud]
    related_skills: [concept-diagrams, excalidraw]
---

# Architecture Diagram Skill

Generate professional, dark-themed technical architecture diagrams as standalone HTML files with inline SVG graphics. No external tools, no API keys, no rendering libraries — just write the HTML file and open it in a browser.

## Scope

**Best suited for:**
- Software system architecture (frontend / backend / database layers)
- Cloud infrastructure (VPC, regions, subnets, managed services)
- Microservice / service-mesh topology
- Database + API map, deployment diagrams
- Anything with a tech-infra subject that fits a dark, grid-backed aesthetic

**Look elsewhere first for:**
- Physics, chemistry, math, biology, or other scientific subjects
- Physical objects (vehicles, hardware, anatomy, cross-sections)
- Floor plans, narrative journeys, educational / textbook-style visuals
- Hand-drawn whiteboard sketches (consider `excalidraw`)
- Animated explainers (consider an animation skill)

If a more specialized skill is available for the subject, prefer that. If none fits, this skill can also serve as a general SVG diagram fallback — the output will just carry the dark tech aesthetic described below.

Based on [Cocoon AI''s architecture-diagram-generator](https://github.com/Cocoon-AI/architecture-diagram-generator) (MIT).

## Workflow

1. User describes their system architecture (components, connections, technologies)
2. Generate the HTML file following the design system below
3. Save with `write_file` to a `.html` file (e.g. `~/architecture-diagram.html`)
4. User opens in any browser — works offline, no dependencies

### Output Location

Save diagrams to a user-specified path, or default to the current working directory:
```
./[project-name]-architecture.html
```

### Preview

After saving, suggest the user open it:
```bash
# macOS
open ./my-architecture.html
# Linux
xdg-open ./my-architecture.html
```

## Design System & Visual Language

### Color Palette (Semantic Mapping)

Use specific `rgba` fills and hex strokes to categorize components:

| Component Type | Fill (rgba) | Stroke (Hex) |
| :--- | :--- | :--- |
| **Frontend** | `rgba(8, 51, 68, 0.4)` | `#22d3ee` (cyan-400) |
| **Backend** | `rgba(6, 78, 59, 0.4)` | `#34d399` (emerald-400) |
| **Database** | `rgba(76, 29, 149, 0.4)` | `#a78bfa` (violet-400) |
| **AWS/Cloud** | `rgba(120, 53, 15, 0.3)` | `#fbbf24` (amber-400) |
| **Security** | `rgba(136, 19, 55, 0.4)` | `#fb7185` (rose-400) |
| **Message Bus** | `rgba(251, 146, 60, 0.3)` | `#fb923c` (orange-400) |
| **External** | `rgba(30, 41, 59, 0.5)` | `#94a3b8` (slate-400) |

### Typography & Background
- **Font:** JetBrains Mono (Monospace), loaded from Google Fonts
- **Sizes:** 12px (Names), 9px (Sublabels), 8px (Annotations), 7px (Tiny labels)
- **Background:** Slate-950 (`#020617`) with a subtle 40px grid pattern

```svg
<!-- Background Grid Pattern -->
<pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
  <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1e293b" stroke-width="0.5"/>
</pattern>
```

## Technical Implementation Details

### Component Rendering
Components are rounded rectangles (`rx="6"`) with 1.5px strokes. To prevent arrows from showing through semi-transparent fills, use a **double-rect masking technique**:
1. Draw an opaque background rect (`#0f172a`)
2. Draw the semi-transparent styled rect on top

### Connection Rules
- **Z-Order:** Draw arrows *early* in the SVG (after the grid) so they render behind component boxes
- **Arrowheads:** Defined via SVG markers
- **Security Flows:** Use dashed lines in rose color (`#fb7185`)
- **Boundaries:**
  - *Security Groups:* Dashed (`4,4`), rose color
  - *Regions:* Large dashed (`8,4`), amber color, `rx="12"`
','skills\creative\architecture-diagram\SKILL.md','17a929a97c1de49e14478ed20ec1445919c5bb2efda81ef74371aa7d1a599b78','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:ascii-art:creative','project_skill','skill://simplicio-runtime/ascii-art','skill: ascii-art','---
name: ascii-art
description: "ASCII art: pyfiglet, cowsay, boxes, image-to-ascii."
version: 4.0.0
author: 0xbyt4, Hermes Agent
license: MIT
dependencies: []
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [ASCII, Art, Banners, Creative, Unicode, Text-Art, pyfiglet, figlet, cowsay, boxes]
    related_skills: [excalidraw]

---

# ASCII Art Skill

Multiple tools for different ASCII art needs. All tools are local CLI programs or free REST APIs — no API keys required.

## Tool 1: Text Banners (pyfiglet — local)

Render text as large ASCII art banners. 571 built-in fonts.

### Setup

```bash
pip install pyfiglet --break-system-packages -q
```

### Usage

```bash
python3 -m pyfiglet "YOUR TEXT" -f slant
python3 -m pyfiglet "TEXT" -f doom -w 80    # Set width
python3 -m pyfiglet --list_fonts             # List all 571 fonts
```

### Recommended fonts

| Style | Font | Best for |
|-------|------|----------|
| Clean & modern | `slant` | Project names, headers |
| Bold & blocky | `doom` | Titles, logos |
| Big & readable | `big` | Banners |
| Classic banner | `banner3` | Wide displays |
| Compact | `small` | Subtitles |
| Cyberpunk | `cyberlarge` | Tech themes |
| 3D effect | `3-d` | Splash screens |
| Gothic | `gothic` | Dramatic text |

### Tips

- Preview 2-3 fonts and let the user pick their favorite
- Short text (1-8 chars) works best with detailed fonts like `doom` or `block`
- Long text works better with compact fonts like `small` or `mini`

## Tool 2: Text Banners (asciified API — remote, no install)

Free REST API that converts text to ASCII art. 250+ FIGlet fonts. Returns plain text directly — no parsing needed. Use this when pyfiglet is not installed or as a quick alternative.

### Usage (via terminal curl)

```bash
# Basic text banner (default font)
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello+World"

# With a specific font
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=Slant"
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=Doom"
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=Star+Wars"
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=3-D"
curl -s "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=Banner3"

# List all available fonts (returns JSON array)
curl -s "https://asciified.thelicato.io/api/v2/fonts"
```

### Tips

- URL-encode spaces as `+` in the text parameter
- The response is plain text ASCII art — no JSON wrapping, ready to display
- Font names are case-sensitive; use the fonts endpoint to get exact names
- Works from any terminal with curl — no Python or pip needed

## Tool 3: Cowsay (Message Art)

Classic tool that wraps text in a speech bubble with an ASCII character.

### Setup

```bash
sudo apt install cowsay -y    # Debian/Ubuntu
# brew install cowsay         # macOS
```

### Usage

```bash
cowsay "Hello World"
cowsay -f tux "Linux rules"       # Tux the penguin
cowsay -f dragon "Rawr!"          # Dragon
cowsay -f stegosaurus "Roar!"     # Stegosaurus
cowthink "Hmm..."                  # Thought bubble
cowsay -l                          # List all characters
```

### Available characters (50+)

`beavis.zen`, `bong`, `bunny`, `cheese`, `daemon`, `default`, `dragon`,
`dragon-and-cow`, `elephant`, `eyes`, `flaming-skull`, `ghostbusters`,
`hellokitty`, `kiss`, `kitty`, `koala`, `luke-koala`, `mech-and-cow`,
`meow`, `moofasa`, `moose`, `ren`, `sheep`, `skeleton`, `small`,
`stegosaurus`, `stimpy`, `supermilker`, `surgery`, `three-eyes`,
`turkey`, `turtle`, `tux`, `udder`, `vader`, `vader-koala`, `www`

### Eye/tongue modifiers

```bash
cowsay -b "Borg"       # =_= eyes
cowsay -d "Dead"       # x_x eyes
cowsay -g "Greedy"     # $_$ eyes
cowsay -p "Paranoid"   # @_@ eyes
cowsay -s "Stoned"     # *_* eyes
cowsay -w "Wired"      # O_O eyes
cowsay -e "OO" "Msg"   # Custom eyes
cowsay -T "U " "Msg"   # Custom tongue
```

## Tool 4: Boxes (Decorative Borders)

Draw decorative ASCII art borders/frames around any text. 70+ built-in designs.

### Setup

```bash
sudo apt install boxes ','skills\creative\ascii-art\SKILL.md','663a6fb34c0a65758d54aca0a136e96297322a61e7e925e91303fa958cbcd69b','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:ascii-video:creative','project_skill','skill://simplicio-runtime/ascii-video','skill: ascii-video','---
name: ascii-video
description: "ASCII video: convert video/audio to colored ASCII MP4/GIF."
platforms: [linux, macos, windows]
---

# ASCII Video Production Pipeline

## When to use

Use when users request: ASCII video, text art video, terminal-style video, character art animation, retro text visualization, audio visualizer in ASCII, converting video to ASCII art, matrix-style effects, or any animated ASCII output.

## What''s inside

Production pipeline for ASCII art video — any format. Converts video/audio/images/generative input into colored ASCII character video output (MP4, GIF, image sequence). Covers: video-to-ASCII conversion, audio-reactive music visualizers, generative ASCII art animations, hybrid video+audio reactive, text/lyrics overlays, real-time terminal rendering.

## Creative Standard

This is visual art. ASCII characters are the medium; cinema is the standard.

**Before writing a single line of code**, articulate the creative concept. What is the mood? What visual story does this tell? What makes THIS project different from every other ASCII video? The user''s prompt is a starting point — interpret it with creative ambition, not literal transcription.

**First-render excellence is non-negotiable.** The output must be visually striking without requiring revision rounds. If something looks generic, flat, or like "AI-generated ASCII art," it is wrong — rethink the creative concept before shipping.

**Go beyond the reference vocabulary.** The effect catalogs, shader presets, and palette libraries in the references are a starting vocabulary. For every project, combine, modify, and invent new patterns. The catalog is a palette of paints — you write the painting.

**Be proactively creative.** Extend the skill''s vocabulary when the project calls for it. If the references don''t have what the vision demands, build it. Include at least one visual moment the user didn''t ask for but will appreciate — a transition, an effect, a color choice that elevates the whole piece.

**Cohesive aesthetic over technical correctness.** All scenes in a video must feel connected by a unifying visual language — shared color temperature, related character palettes, consistent motion vocabulary. A technically correct video where every scene uses a random different effect is an aesthetic failure.

**Dense, layered, considered.** Every frame should reward viewing. Never flat black backgrounds. Always multi-grid composition. Always per-scene variation. Always intentional color.

## Modes

| Mode | Input | Output | Reference |
|------|-------|--------|-----------|
| **Video-to-ASCII** | Video file | ASCII recreation of source footage | `references/inputs.md` § Video Sampling |
| **Audio-reactive** | Audio file | Generative visuals driven by audio features | `references/inputs.md` § Audio Analysis |
| **Generative** | None (or seed params) | Procedural ASCII animation | `references/effects.md` |
| **Hybrid** | Video + audio | ASCII video with audio-reactive overlays | Both input refs |
| **Lyrics/text** | Audio + text/SRT | Timed text with visual effects | `references/inputs.md` § Text/Lyrics |
| **TTS narration** | Text quotes + TTS API | Narrated testimonial/quote video with typed text | `references/inputs.md` § TTS Integration |

## Stack

Single self-contained Python script per project. No GPU required.

| Layer | Tool | Purpose |
|-------|------|---------|
| Core | Python 3.10+, NumPy | Math, array ops, vectorized effects |
| Signal | SciPy | FFT, peak detection (audio modes) |
| Imaging | Pillow (PIL) | Font rasterization, frame decoding, image I/O |
| Video I/O | ffmpeg (CLI) | Decode input, encode output, mux audio |
| Parallel | concurrent.futures | N workers for batch/clip rendering |
| TTS | ElevenLabs API (optional) | Generate narration clips |
| Optional | OpenCV | Video frame sampling, edge detection |

## Pipeline Architecture

Every mode follows the same 6-stage pipeline:

```
INPUT → ANALYZE → SCENE_FN → TONEMAP → SHADE → ENCODE
```

1. **INPUT** — Load/decode source material (video frames, audio samples, images, or nothi','skills\creative\ascii-video\SKILL.md','f00a59b42939d2fa82de23c4f32203dc50f4c72dc27161e06f1605497f8d22c3','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:baoyu-article-illustrator:creative','project_skill','skill://simplicio-runtime/baoyu-article-illustrator','skill: baoyu-article-illustrator','---
name: baoyu-article-illustrator
description: "Article illustrations: type × style × palette consistency."
version: 1.57.0
author: 宝玉 (JimLiu)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [article-illustration, creative, image-generation]
    category: creative
    homepage: https://github.com/JimLiu/baoyu-skills#baoyu-article-illustrator
---

# Article Illustrator

Adapted from [baoyu-article-illustrator](https://github.com/JimLiu/baoyu-skills) for Hermes Agent''s tool ecosystem.

Analyze articles, identify illustration positions, generate images with **Type × Style × Palette** consistency.

## When to Use

Trigger this skill when the user asks to illustrate an article, add images to an article, generate illustrations for content, or uses phrases like "为文章配图", "illustrate article", or "add images". The user provides an article (file path or pasted content) and optionally specifies type, style, palette, or density.

## Three Dimensions

| Dimension | Controls | Examples |
|-----------|----------|----------|
| **Type** | Information structure | infographic, scene, flowchart, comparison, framework, timeline |
| **Style** | Rendering approach | notion, warm, minimal, blueprint, watercolor, elegant |
| **Palette** | Color scheme (optional) | macaron, warm, neon — overrides style''s default colors |

Combine freely: `type=infographic, style=vector-illustration, palette=macaron`.

Or use presets: `edu-visual` → type + style + palette in one shot. See [style-presets.md](references/style-presets.md).

## Types

| Type | Best For |
|------|----------|
| `infographic` | Data, metrics, technical |
| `scene` | Narratives, emotional |
| `flowchart` | Processes, workflows |
| `comparison` | Side-by-side, options |
| `framework` | Models, architecture |
| `timeline` | History, evolution |

## Styles

See [references/styles.md](references/styles.md) for Core Styles, the full gallery, and Type × Style compatibility.

## Output Structure

```
{output-dir}/
├── source-{slug}.{ext}    # Only for pasted content
├── outline.md
├── prompts/
│   └── NN-{type}-{slug}.md
└── NN-{type}-{slug}.png
```

**Default output directory**:

| Input | Output Directory | Markdown Insert Path |
|-------|------------------|----------------------|
| Article file path | `{article-dir}/imgs/` | `imgs/NN-{type}-{slug}.png` |
| Pasted content | `illustrations/{topic-slug}/` (cwd) | `illustrations/{topic-slug}/NN-{type}-{slug}.png` |

If the user asks for a different layout (e.g., images alongside the article, or a `illustrations/` subdirectory), honor that.

**Slug**: 2-4 words, kebab-case. **Conflict**: append `-YYYYMMDD-HHMMSS`.

## Core Principles

- **Visualize concepts, not metaphors** — if the article uses a metaphor (e.g., "电锯切西瓜"), illustrate the underlying concept, not the literal image.
- **Labels use article data** — actual numbers, terms, and quotes from the article, not generic placeholders.
- **Prompt files are reproducibility records** — every illustration must have a saved prompt file under `prompts/` before any image is generated.
- **Strip secrets** — scan source content for API keys, tokens, or credentials before writing anything to disk.

## Workflow

```
- [ ] Step 1: Detect reference images (if provided)
- [ ] Step 2: Analyze content
- [ ] Step 3: Confirm settings (clarify tool, one question at a time)
- [ ] Step 4: Generate outline
- [ ] Step 5: Generate prompts
- [ ] Step 6: Generate images (image_generate)
- [ ] Step 7: Finalize
```

### Step 1: Detect Reference Images

If the user supplies reference images (paths pasted inline, attachments, or a URL):

1. For each reference, call `vision_analyze` with the path/URL and a question asking for style, palette, composition, and subject. Record the returned description in `{output-dir}/references/NN-ref-{slug}.md` via `write_file`.
2. **Do not** try to copy the binary via `write_file` / `read_file` — those are text-only. If you want a local copy for the record, use `terminal` (`cp "$src" "{output-dir}/references/NN-ref-{slug}.{ext}"`). The skill itself never need','skills\creative\baoyu-article-illustrator\SKILL.md','c5262418d7b5e0dba01ecab692a50be729890d7db7a9d9dffb2349ad3dedbffb','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:baoyu-comic:creative','project_skill','skill://simplicio-runtime/baoyu-comic','skill: baoyu-comic','---
name: baoyu-comic
description: "Knowledge comics (知识漫画): educational, biography, tutorial."
version: 1.56.1
author: 宝玉 (JimLiu)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [comic, knowledge-comic, creative, image-generation]
    homepage: https://github.com/JimLiu/baoyu-skills#baoyu-comic
---

# Knowledge Comic Creator

Adapted from [baoyu-comic](https://github.com/JimLiu/baoyu-skills) for Hermes Agent''s tool ecosystem.

Create original knowledge comics with flexible art style × tone combinations.

## When to Use

Trigger this skill when the user asks to create a knowledge/educational comic, biography comic, tutorial comic, or uses terms like "知识漫画", "教育漫画", or "Logicomix-style". The user provides content (text, file path, URL, or topic) and optionally specifies art style, tone, layout, aspect ratio, or language.

## Reference Images

Hermes'' `image_generate` tool is **prompt-only** — it accepts a text prompt and an aspect ratio, and returns an image URL. It does **NOT** accept reference images. When the user supplies a reference image, use it to **extract traits in text** that get embedded in every page prompt:

**Intake**: Accept file paths when the user provides them (or pastes images in conversation).
- File path(s) → copy to `refs/NN-ref-{slug}.{ext}` alongside the comic output for provenance
- Pasted image with no path → ask the user for the path via `clarify`, or extract style traits verbally as a text fallback
- No reference → skip this section

**Usage modes** (per reference):

| Usage | Effect |
|-------|--------|
| `style` | Extract style traits (line treatment, texture, mood) and append to every page''s prompt body |
| `palette` | Extract hex colors and append to every page''s prompt body |
| `scene` | Extract scene composition or subject notes and append to the relevant page(s) |

**Record in each page''s prompt frontmatter** when refs exist:

```yaml
references:
  - ref_id: 01
    filename: 01-ref-scene.png
    usage: style
    traits: "muted earth tones, soft-edged ink wash, low-contrast backgrounds"
```

Character consistency is driven by **text descriptions** in `characters/characters.md` (written in Step 3) that get embedded inline in every page prompt (Step 5). The optional PNG character sheet generated in Step 7.1 is a human-facing review artifact, not an input to `image_generate`.

## Options

### Visual Dimensions

| Option | Values | Description |
|--------|--------|-------------|
| Art | ligne-claire (default), manga, realistic, ink-brush, chalk, minimalist | Art style / rendering technique |
| Tone | neutral (default), warm, dramatic, romantic, energetic, vintage, action | Mood / atmosphere |
| Layout | standard (default), cinematic, dense, splash, mixed, webtoon, four-panel | Panel arrangement |
| Aspect | 3:4 (default, portrait), 4:3 (landscape), 16:9 (widescreen) | Page aspect ratio |
| Language | auto (default), zh, en, ja, etc. | Output language |
| Refs | File paths | Reference images used for style / palette trait extraction (not passed to the image model). See [Reference Images](#reference-images) above. |

### Partial Workflow Options

| Option | Description |
|--------|-------------|
| Storyboard only | Generate storyboard only, skip prompts and images |
| Prompts only | Generate storyboard + prompts, skip images |
| Images only | Generate images from existing prompts directory |
| Regenerate N | Regenerate specific page(s) only (e.g., `3` or `2,5,8`) |

Details: [references/partial-workflows.md](references/partial-workflows.md)

### Art, Tone & Preset Catalogue

- **Art styles** (6): `ligne-claire`, `manga`, `realistic`, `ink-brush`, `chalk`, `minimalist`. Full definitions at `references/art-styles/<style>.md`.
- **Tones** (7): `neutral`, `warm`, `dramatic`, `romantic`, `energetic`, `vintage`, `action`. Full definitions at `references/tones/<tone>.md`.
- **Presets** (5) with special rules beyond plain art+tone:

  | Preset | Equivalent | Hook |
  |--------|-----------|------|
  | `ohmsha` | manga + neutral | Visual metaphors, no talking heads, gadget ','skills\creative\baoyu-comic\SKILL.md','887d529fae27fdb2ec44e0e209867e31c6d5ef7eefe67ffea0ea2265d5fc1b63','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:baoyu-infographic:creative','project_skill','skill://simplicio-runtime/baoyu-infographic','skill: baoyu-infographic','---
name: baoyu-infographic
description: "Infographics: 21 layouts x 21 styles (信息图, 可视化)."
version: 1.56.1
author: 宝玉 (JimLiu)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [infographic, visual-summary, creative, image-generation]
    homepage: https://github.com/JimLiu/baoyu-skills#baoyu-infographic
---

# Infographic Generator

Adapted from [baoyu-infographic](https://github.com/JimLiu/baoyu-skills) for Hermes Agent''s tool ecosystem.

Two dimensions: **layout** (information structure) × **style** (visual aesthetics). Freely combine any layout with any style.

## When to Use

Trigger this skill when the user asks to create an infographic, visual summary, information graphic, or uses terms like "信息图", "可视化", or "高密度信息大图". The user provides content (text, file path, URL, or topic) and optionally specifies layout, style, aspect ratio, or language.

## Options

| Option | Values |
|--------|--------|
| Layout | 21 options (see Layout Gallery), default: bento-grid |
| Style | 21 options (see Style Gallery), default: craft-handmade |
| Aspect | Named: landscape (16:9), portrait (9:16), square (1:1). Custom: any W:H ratio (e.g., 3:4, 4:3, 2.35:1) |
| Language | en, zh, ja, etc. |

## Layout Gallery

| Layout | Best For |
|--------|----------|
| `linear-progression` | Timelines, processes, tutorials |
| `binary-comparison` | A vs B, before-after, pros-cons |
| `comparison-matrix` | Multi-factor comparisons |
| `hierarchical-layers` | Pyramids, priority levels |
| `tree-branching` | Categories, taxonomies |
| `hub-spoke` | Central concept with related items |
| `structural-breakdown` | Exploded views, cross-sections |
| `bento-grid` | Multiple topics, overview (default) |
| `iceberg` | Surface vs hidden aspects |
| `bridge` | Problem-solution |
| `funnel` | Conversion, filtering |
| `isometric-map` | Spatial relationships |
| `dashboard` | Metrics, KPIs |
| `periodic-table` | Categorized collections |
| `comic-strip` | Narratives, sequences |
| `story-mountain` | Plot structure, tension arcs |
| `jigsaw` | Interconnected parts |
| `venn-diagram` | Overlapping concepts |
| `winding-roadmap` | Journey, milestones |
| `circular-flow` | Cycles, recurring processes |
| `dense-modules` | High-density modules, data-rich guides |

Full definitions: `references/layouts/<layout>.md`

## Style Gallery

| Style | Description |
|-------|-------------|
| `craft-handmade` | Hand-drawn, paper craft (default) |
| `claymation` | 3D clay figures, stop-motion |
| `kawaii` | Japanese cute, pastels |
| `storybook-watercolor` | Soft painted, whimsical |
| `chalkboard` | Chalk on black board |
| `cyberpunk-neon` | Neon glow, futuristic |
| `bold-graphic` | Comic style, halftone |
| `aged-academia` | Vintage science, sepia |
| `corporate-memphis` | Flat vector, vibrant |
| `technical-schematic` | Blueprint, engineering |
| `origami` | Folded paper, geometric |
| `pixel-art` | Retro 8-bit |
| `ui-wireframe` | Grayscale interface mockup |
| `subway-map` | Transit diagram |
| `ikea-manual` | Minimal line art |
| `knolling` | Organized flat-lay |
| `lego-brick` | Toy brick construction |
| `pop-laboratory` | Blueprint grid, coordinate markers, lab precision |
| `morandi-journal` | Hand-drawn doodle, warm Morandi tones |
| `retro-pop-grid` | 1970s retro pop art, Swiss grid, thick outlines |
| `hand-drawn-edu` | Macaron pastels, hand-drawn wobble, stick figures |

Full definitions: `references/styles/<style>.md`

## Recommended Combinations

| Content Type | Layout + Style |
|--------------|----------------|
| Timeline/History | `linear-progression` + `craft-handmade` |
| Step-by-step | `linear-progression` + `ikea-manual` |
| A vs B | `binary-comparison` + `corporate-memphis` |
| Hierarchy | `hierarchical-layers` + `craft-handmade` |
| Overlap | `venn-diagram` + `craft-handmade` |
| Conversion | `funnel` + `corporate-memphis` |
| Cycles | `circular-flow` + `craft-handmade` |
| Technical | `structural-breakdown` + `technical-schematic` |
| Metrics | `dashboard` + `corporate-memphis` |
| Educational | `bento-grid` + `chalkboard','skills\creative\baoyu-infographic\SKILL.md','c91946447f085c0b6cfffbf835d7ae82a2f20e00058f00e5b1eaf5aa0e03c593','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:blender-mcp:creative','project_skill','skill://simplicio-runtime/blender-mcp','skill: blender-mcp','---
name: blender-mcp
description: Control Blender directly from Hermes via socket connection to the blender-mcp addon. Create 3D objects, materials, animations, and run arbitrary Blender Python (bpy) code. Use when user wants to create or modify anything in Blender.
version: 1.0.0
requires: Blender 4.3+ (desktop instance required, headless not supported)
author: alireza78a
tags: [blender, 3d, animation, modeling, bpy, mcp]
platforms: [linux, macos, windows]
---

# Blender MCP

Control a running Blender instance from Hermes via socket on TCP port 9876.

## Setup (one-time)

### 1. Install the Blender addon

    curl -sL https://raw.githubusercontent.com/ahujasid/blender-mcp/main/addon.py -o ~/Desktop/blender_mcp_addon.py

In Blender:
    Edit > Preferences > Add-ons > Install > select blender_mcp_addon.py
    Enable "Interface: Blender MCP"

### 2. Start the socket server in Blender

Press N in Blender viewport to open sidebar.
Find "BlenderMCP" tab and click "Start Server".

### 3. Verify connection

    nc -z -w2 localhost 9876 && echo "OPEN" || echo "CLOSED"

## Protocol

Plain UTF-8 JSON over TCP -- no length prefix.

Send:     {"type": "<command>", "params": {<kwargs>}}
Receive:  {"status": "success", "result": <value>}
          {"status": "error",   "message": "<reason>"}

## Available Commands

| type                    | params            | description                     |
|-------------------------|-------------------|---------------------------------|
| execute_code            | code (str)        | Run arbitrary bpy Python code   |
| get_scene_info          | (none)            | List all objects in scene       |
| get_object_info         | object_name (str) | Details on a specific object    |
| get_viewport_screenshot | (none)            | Screenshot of current viewport  |

## Python Helper

Use this inside execute_code tool calls:

    import socket, json

    def blender_exec(code: str, host="localhost", port=9876, timeout=15):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, port))
        s.settimeout(timeout)
        payload = json.dumps({"type": "execute_code", "params": {"code": code}})
        s.sendall(payload.encode("utf-8"))
        buf = b""
        while True:
            try:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
                try:
                    json.loads(buf.decode("utf-8"))
                    break
                except json.JSONDecodeError:
                    continue
            except socket.timeout:
                break
        s.close()
        return json.loads(buf.decode("utf-8"))

## Common bpy Patterns

### Clear scene
    bpy.ops.object.select_all(action=''SELECT'')
    bpy.ops.object.delete()

### Add mesh objects
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(0, 0, 0))
    bpy.ops.mesh.primitive_cube_add(size=2, location=(3, 0, 0))
    bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=2, location=(-3, 0, 0))

### Create and assign material
    mat = bpy.data.materials.new(name="MyMat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (R, G, B, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.3
    bsdf.inputs["Metallic"].default_value = 0.0
    obj.data.materials.append(mat)

### Keyframe animation
    obj.location = (0, 0, 0)
    obj.keyframe_insert(data_path="location", frame=1)
    obj.location = (0, 0, 3)
    obj.keyframe_insert(data_path="location", frame=60)

### Render to file
    bpy.context.scene.render.filepath = "/tmp/render.png"
    bpy.context.scene.render.engine = ''CYCLES''
    bpy.ops.render.render(write_still=True)

## Pitfalls

- Must check socket is open before running (nc -z localhost 9876)
- Addon server must be started inside Blender each session (N-panel > BlenderMCP > Connect)
- Break complex scenes into multiple smaller execute_code calls to avoid timeouts
- Render output path must be absolute (/tmp/...) not relative
- shade_smooth()','skills\creative\blender-mcp\SKILL.md','407c03c1a8312ad5b436a12a5e7deba3e7b0ee387bd46381e75985962a1cb1ed','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:claude-design:creative','project_skill','skill://simplicio-runtime/claude-design','skill: claude-design','---
name: claude-design
description: Design one-off HTML artifacts (landing, deck, prototype).
version: 1.0.0
author: BadTechBandit
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [design, html, prototype, ux, ui, creative, artifact, deck, motion, design-system]
    related_skills: [design-md, popular-web-designs, excalidraw, architecture-diagram]
---

# Claude Design for CLI/API Agents

Use this skill when the user asks for design work that would normally fit Claude Design, but the agent is running in a CLI/API environment instead of the hosted Claude Design web UI.

The goal is to preserve Claude Design''s useful design behavior and taste while removing hosted-tool plumbing that does not exist in normal agent environments.

**Before starting, check for other web-design skills like `popular-web-designs` (ready-to-paste design systems for Stripe, Linear, Vercel, Notion, etc.) and `design-md` (Google''s DESIGN.md token spec format).** If the user wants a known brand''s look, load `popular-web-designs` alongside this one and let it supply the visual vocabulary. If the deliverable is a token spec file rather than a rendered artifact, use `design-md` instead. Full decision table below.

## When To Use This Skill vs `popular-web-designs` vs `design-md`

Hermes has three design-related skills under `skills/creative/`. They do different jobs — load the right one (or combine them):

| Skill | What it gives you | Use when the user wants... |
|---|---|---|
| **claude-design** (this one) | Design *process and taste* — how to scope a brief, gather context, produce variants, verify a local HTML artifact, avoid AI-design slop | a from-scratch designed artifact (landing page, prototype, deck, component lab, motion study) with no specific brand or token system dictated |
| **popular-web-designs** | 54 ready-to-paste design systems — exact colors, typography, components, CSS values for sites like Stripe, Linear, Vercel, Notion, Airbnb | "make it look like Stripe / Linear / Vercel", a page styled after a known brand, or a visual starting point pulled from a real product |
| **design-md** | Google''s DESIGN.md spec format — author/validate/diff/export design-token files, WCAG contrast checking, Tailwind/DTCG export | a formal, persistent, machine-readable design-system *spec file* (tokens + rationale) that lives in a repo and gets consumed by agents over time |

Rule of thumb:

- **Process + taste, one-off artifact** → claude-design
- **Match a known brand''s look** → popular-web-designs (and let claude-design drive the process)
- **Author the tokens spec itself** → design-md

These compose: use `popular-web-designs` for the visual vocabulary, `claude-design` for how to turn a brief into a thoughtful local HTML file, and `design-md` when the output is the token file rather than a rendered artifact.

## Runtime Mode

You are running in **CLI/API mode**, not the Claude Design hosted web UI.

Ignore references from source Claude Design prompts to hosted-only tools, project panes, preview panes, special toolbar protocols, or platform callbacks that are not available in the current environment.

Examples of hosted-tool concepts to ignore or remap:

- `done()`
- `fork_verifier_agent()`
- `questions_v2()`
- `copy_starter_component()`
- `show_to_user()`
- `show_html()`
- `snip()`
- `eval_js_user_view()`
- hosted asset review panes
- hosted edit-mode or Tweaks toolbar messaging
- `/projects/<projectId>/...` cross-project paths
- built-in `window.claude.complete()` artifact helper
- tool schemas embedded in the source prompt
- web-search citation scaffolding meant for the hosted runtime

Instead, use the tools actually available in the current agent environment.

Default deliverable:

- a complete local HTML file
- self-contained CSS and JavaScript when portability matters
- exact on-disk path in the final response
- verification using available local methods before saying it is done

If the user asks for implementation in an existing repo, generate code in the repo''s actual stack instead of forcing a standalone HTML artifac','skills\creative\claude-design\SKILL.md','69eca13c824a92508b9684930865d806fb932c4b3e3cd10314a22d6d9c7384bb','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:comfyui:creative','project_skill','skill://simplicio-runtime/comfyui','skill: comfyui','---
name: comfyui
description: "Generate images, video, and audio with ComfyUI — install, launch, manage nodes/models, run workflows with parameter injection. Uses the official comfy-cli for lifecycle and direct REST/WebSocket API for execution."
version: 5.1.0
author: [kshitijk4poor, alt-glitch, purzbeats]
license: MIT
platforms: [macos, linux, windows]
compatibility: "Requires ComfyUI (local, Comfy Desktop, or Comfy Cloud) and comfy-cli (auto-installed via pipx/uvx by the setup script)."
prerequisites:
  commands: ["python3"]
setup:
  help: "Run scripts/hardware_check.py FIRST to decide local vs Comfy Cloud; then scripts/comfyui_setup.sh auto-installs locally (or use Cloud API key for platform.comfy.org)."
metadata:
  hermes:
    tags:
      - comfyui
      - image-generation
      - stable-diffusion
      - flux
      - sd3
      - wan-video
      - hunyuan-video
      - creative
      - generative-ai
      - video-generation
    related_skills: [stable-diffusion-image-generation, image_gen]
    category: creative
---

# ComfyUI

Generate images, video, audio, and 3D content through ComfyUI using the
official `comfy-cli` for setup/lifecycle and direct REST/WebSocket API
for workflow execution.

## What''s in this skill

**Reference docs (`references/`):**

- `official-cli.md` — every `comfy ...` command, with flags
- `rest-api.md` — REST + WebSocket endpoints (local + cloud), payload schemas
- `workflow-format.md` — API-format JSON, common node types, param mapping
- `template-integrity.md` — converting `comfyui-workflow-templates` from
  editor format to API format: Reroute bypass, dotted dynamic-input keys
  (`values.a`, `resize_type.width`), Cloud quirks (302 redirect, 1 concurrent
  free-tier job, 1080p VRAM ceiling), Discord-compatible ffmpeg stitch.
  Authored by [@purzbeats](https://github.com/purzbeats). Load this whenever
  you''re starting from an official template.

**Scripts (`scripts/`):**

| Script | Purpose |
|--------|---------|
| `_common.py` | Shared HTTP, cloud routing, node catalogs (don''t run directly) |
| `hardware_check.py` | Probe GPU/VRAM/disk → recommend local vs Comfy Cloud |
| `comfyui_setup.sh` | Hardware check + comfy-cli + ComfyUI install + launch + verify |
| `extract_schema.py` | Read a workflow → list controllable params + model deps |
| `check_deps.py` | Check workflow against running server → list missing nodes/models |
| `auto_fix_deps.py` | Run check_deps then `comfy node install` / `comfy model download` |
| `run_workflow.py` | Inject params, submit, monitor, download outputs (HTTP or WS) |
| `run_batch.py` | Submit a workflow N times with sweeps, parallel up to your tier |
| `ws_monitor.py` | Real-time WebSocket viewer for executing jobs (live progress) |
| `health_check.py` | Verification checklist runner — comfy-cli + server + models + smoke test |
| `fetch_logs.py` | Pull traceback / status messages for a given prompt_id |

**Example workflows (`workflows/`):** SD 1.5, SDXL, Flux Dev, SDXL img2img,
SDXL inpaint, ESRGAN upscale, AnimateDiff video, Wan T2V. See
`workflows/README.md`.

## When to Use

- User asks to generate images with Stable Diffusion, SDXL, Flux, SD3, etc.
- User wants to run a specific ComfyUI workflow file
- User wants to chain generative steps (txt2img → upscale → face restore)
- User needs ControlNet, inpainting, img2img, or other advanced pipelines
- User asks to manage ComfyUI queue, check models, or install custom nodes
- User wants video/audio/3D generation via AnimateDiff, Hunyuan, Wan, AudioCraft, etc.

## Architecture: Two Layers

```
┌─────────────────────────────────────────────────────┐
│ Layer 1: comfy-cli (official lifecycle tool)        │
│   Setup, server lifecycle, custom nodes, models     │
│   → comfy install / launch / stop / node / model    │
└─────────────────────────┬───────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────┐
│ Layer 2: REST/WebSocket API + skill scripts         │
│   Workflow execution, param injection, monitoring   │
│   POST /api/prompt, GET /api/view, WS /ws      ','skills\creative\comfyui\SKILL.md','3849ec3833cbdf6377c5c066d79bed5d7e89e32b0e11be377ed81d8aec48ed52','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:concept-diagrams:creative','project_skill','skill://simplicio-runtime/concept-diagrams','skill: concept-diagrams','---
name: concept-diagrams
description: Generate flat, minimal light/dark-aware SVG diagrams as standalone HTML files, using a unified educational visual language with 9 semantic color ramps, sentence-case typography, and automatic dark mode. Best suited for educational and non-software visuals — physics setups, chemistry mechanisms, math curves, physical objects (aircraft, turbines, smartphones, mechanical watches), anatomy, floor plans, cross-sections, narrative journeys (lifecycle of X, process of Y), hub-spoke system integrations (smart city, IoT), and exploded layer views. If a more specialized skill exists for the subject (dedicated software/cloud architecture, hand-drawn sketches, animated explainers, etc.), prefer that — otherwise this skill can also serve as a general-purpose SVG diagram fallback with a clean educational look. Ships with 15 example diagrams.
version: 0.1.0
author: v1k22 (original PR), ported into hermes-agent
license: MIT
dependencies: []
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [diagrams, svg, visualization, education, physics, chemistry, engineering]
    related_skills: [architecture-diagram, excalidraw, generative-widgets]
---

# Concept Diagrams

Generate production-quality SVG diagrams with a unified flat, minimal design system. Output is a single self-contained HTML file that renders identically in any modern browser, with automatic light/dark mode.

## Scope

**Best suited for:**
- Physics setups, chemistry mechanisms, math curves, biology
- Physical objects (aircraft, turbines, smartphones, mechanical watches, cells)
- Anatomy, cross-sections, exploded layer views
- Floor plans, architectural conversions
- Narrative journeys (lifecycle of X, process of Y)
- Hub-spoke system integrations (smart city, IoT networks, electricity grids)
- Educational / textbook-style visuals in any domain
- Quantitative charts (grouped bars, energy profiles)

**Look elsewhere first for:**
- Dedicated software / cloud infrastructure architecture with a dark tech aesthetic (consider `architecture-diagram` if available)
- Hand-drawn whiteboard sketches (consider `excalidraw` if available)
- Animated explainers or video output (consider an animation skill)

If a more specialized skill is available for the subject, prefer that. If none fits, this skill can serve as a general-purpose SVG diagram fallback — the output will carry the clean educational aesthetic described below, which is a reasonable default for almost any subject.

## Workflow

1. Decide on the diagram type (see Diagram Types below).
2. Lay out components using the Design System rules.
3. Write the full HTML page using `templates/template.html` as the wrapper — paste your SVG where the template says `<!-- PASTE SVG HERE -->`.
4. Save as a standalone `.html` file (for example `~/my-diagram.html` or `./my-diagram.html`).
5. User opens it directly in a browser — no server, no dependencies.

Optional: if the user wants a browsable gallery of multiple diagrams, see "Local Preview Server" at the bottom.

Load the HTML template:
```
skill_view(name="concept-diagrams", file_path="templates/template.html")
```

The template embeds the full CSS design system (`c-*` color classes, text classes, light/dark variables, arrow marker styles). The SVG you generate relies on these classes being present on the hosting page.

---

## Design System

### Philosophy

- **Flat**: no gradients, drop shadows, blur, glow, or neon effects.
- **Minimal**: show the essential. No decorative icons inside boxes.
- **Consistent**: same colors, spacing, typography, and stroke widths across every diagram.
- **Dark-mode ready**: all colors auto-adapt via CSS classes — no per-mode SVG.

### Color Palette

9 color ramps, each with 7 stops. Put the class name on a `<g>` or shape element; the template CSS handles both modes.

| Class      | 50 (lightest) | 100     | 200     | 400     | 600     | 800     | 900 (darkest) |
|------------|---------------|---------|---------|---------|---------|---------|---------------|
| `c-purple` | #EEEDFE | #CECBF6 | #AFA9EC | #7F77D','skills\creative\concept-diagrams\SKILL.md','434eb40d8bdfeb2b111622e50441deb21d280ab13849129203f0c31f4ab72365','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:creative-ideation:creative','project_skill','skill://simplicio-runtime/creative-ideation','skill: creative-ideation','---
name: ideation
title: Creative Ideation — Constraint-Driven Project Generation
description: "Generate project ideas via creative constraints."
version: 1.0.0
author: SHL0MS
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Creative, Ideation, Projects, Brainstorming, Inspiration]
    category: creative
    requires_toolsets: []
---

# Creative Ideation

## When to use

Use when the user says ''I want to build something'', ''give me a project idea'', ''I''m bored'', ''what should I make'', ''inspire me'', or any variant of ''I have tools but no direction''. Works for code, art, hardware, writing, tools, and anything that can be made.

Generate project ideas through creative constraints. Constraint + direction = creativity.

## How It Works

1. **Pick a constraint** from the library below — random, or matched to the user''s domain/mood
2. **Interpret it broadly** — a coding prompt can become a hardware project, an art prompt can become a CLI tool
3. **Generate 3 concrete project ideas** that satisfy the constraint
4. **If they pick one, build it** — create the project, write the code, ship it

## The Rule

Every prompt is interpreted as broadly as possible. "Does this include X?" → Yes. The prompts provide direction and mild constraint. Without either, there is no creativity.

## Constraint Library

### For Developers

**Solve your own itch:**
Build the tool you wished existed this week. Under 50 lines. Ship it today.

**Automate the annoying thing:**
What''s the most tedious part of your workflow? Script it away. Two hours to fix a problem that costs you five minutes a day.

**The CLI tool that should exist:**
Think of a command you''ve wished you could type. `git undo-that-thing-i-just-did`. `docker why-is-this-broken`. `npm explain-yourself`. Now build it.

**Nothing new except glue:**
Make something entirely from existing APIs, libraries, and datasets. The only original contribution is how you connect them.

**Frankenstein week:**
Take something that does X and make it do Y. A git repo that plays music. A Dockerfile that generates poetry. A cron job that sends compliments.

**Subtract:**
How much can you remove from a codebase before it breaks? Strip a tool to its minimum viable function. Delete until only the essence remains.

**High concept, low effort:**
A deep idea, lazily executed. The concept should be brilliant. The implementation should take an afternoon. If it takes longer, you''re overthinking it.

### For Makers & Artists

**Blatantly copy something:**
Pick something you admire — a tool, an artwork, an interface. Recreate it from scratch. The learning is in the gap between your version and theirs.

**One million of something:**
One million is both a lot and not that much. One million pixels is a 1MB photo. One million API calls is a Tuesday. One million of anything becomes interesting at scale.

**Make something that dies:**
A website that loses a feature every day. A chatbot that forgets. A countdown to nothing. An exercise in rot, killing, or letting go.

**Do a lot of math:**
Generative geometry, shader golf, mathematical art, computational origami. Time to re-learn what an arcsin is.

### For Anyone

**Text is the universal interface:**
Build something where text is the only interface. No buttons, no graphics, just words in and words out. Text can go in and out of almost anything.

**Start at the punchline:**
Think of something that would be a funny sentence. Work backwards to make it real. "I taught my thermostat to gaslight me" → now build it.

**Hostile UI:**
Make something intentionally painful to use. A password field that requires 47 conditions. A form where every label lies. A CLI that judges your commands.

**Take two:**
Remember an old project. Do it again from scratch. No looking at the original. See what changed about how you think.

See `references/full-prompt-library.md` for 30+ additional constraints across communication, scale, philosophy, transformation, and more.

## Matching Constraints to Users

| User says | Pick from |
|-----------|-----------|
| "I want to build some','skills\creative\creative-ideation\SKILL.md','1145354ec68eac30708cca0324d85f38715e43c56a910c7326ce701ec72f6fec','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:design-md:creative','project_skill','skill://simplicio-runtime/design-md','skill: design-md','---
name: design-md
description: Author/validate/export Google''s DESIGN.md token spec files.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [design, design-system, tokens, ui, accessibility, wcag, tailwind, dtcg, google]
    related_skills: [popular-web-designs, claude-design, excalidraw, architecture-diagram]
---

# DESIGN.md Skill

DESIGN.md is Google''s open spec (Apache-2.0, `google-labs-code/design.md`) for
describing a visual identity to coding agents. One file combines:

- **YAML front matter** — machine-readable design tokens (normative values)
- **Markdown body** — human-readable rationale, organized into canonical sections

Tokens give exact values. Prose tells agents *why* those values exist and how to
apply them. The CLI (`npx @google/design.md`) lints structure + WCAG contrast,
diffs versions for regressions, and exports to Tailwind or W3C DTCG JSON.

## When to use this skill

- User asks for a DESIGN.md file, design tokens, or a design system spec
- User wants consistent UI/brand across multiple projects or tools
- User pastes an existing DESIGN.md and asks to lint, diff, export, or extend it
- User asks to port a style guide into a format agents can consume
- User wants contrast / WCAG accessibility validation on their color palette

For purely visual inspiration or layout examples, use `popular-web-designs`
instead. For *process and taste* when designing a one-off HTML artifact
from scratch (prototype, deck, landing page, component lab), use
`claude-design`. This skill is for the *formal spec file* itself.

## File anatomy

```md
---
version: alpha
name: Heritage
description: Architectural minimalism meets journalistic gravitas.
colors:
  primary: "#1A1C1E"
  secondary: "#6C7278"
  tertiary: "#B8422E"
  neutral: "#F7F5F2"
typography:
  h1:
    fontFamily: Public Sans
    fontSize: 3rem
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  body-md:
    fontFamily: Public Sans
    fontSize: 1rem
rounded:
  sm: 4px
  md: 8px
  lg: 16px
spacing:
  sm: 8px
  md: 16px
  lg: 24px
components:
  button-primary:
    backgroundColor: "{colors.tertiary}"
    textColor: "#FFFFFF"
    rounded: "{rounded.sm}"
    padding: 12px
  button-primary-hover:
    backgroundColor: "{colors.primary}"
---

## Overview

Architectural Minimalism meets Journalistic Gravitas...

## Colors

- **Primary (#1A1C1E):** Deep ink for headlines and core text.
- **Tertiary (#B8422E):** "Boston Clay" — the sole driver for interaction.

## Typography

Public Sans for everything except small all-caps labels...

## Components

`button-primary` is the only high-emphasis action on a page...
```

## Token types

| Type | Format | Example |
|------|--------|---------|
| Color | `#` + hex (sRGB) | `"#1A1C1E"` |
| Dimension | number + unit (`px`, `em`, `rem`) | `48px`, `-0.02em` |
| Token reference | `{path.to.token}` | `{colors.primary}` |
| Typography | object with `fontFamily`, `fontSize`, `fontWeight`, `lineHeight`, `letterSpacing`, `fontFeature`, `fontVariation` | see above |

Component property whitelist: `backgroundColor`, `textColor`, `typography`,
`rounded`, `padding`, `size`, `height`, `width`. Variants (hover, active,
pressed) are **separate component entries** with related key names
(`button-primary-hover`), not nested.

## Canonical section order

Sections are optional, but present ones MUST appear in this order. Duplicate
headings reject the file.

1. Overview (alias: Brand & Style)
2. Colors
3. Typography
4. Layout (alias: Layout & Spacing)
5. Elevation & Depth (alias: Elevation)
6. Shapes
7. Components
8. Do''s and Don''ts

Unknown sections are preserved, not errored. Unknown token names are accepted
if the value type is valid. Unknown component properties produce a warning.

## Workflow: authoring a new DESIGN.md

1. **Ask the user** (or infer) the brand tone, accent color, and typography
   direction. If they provided a site, image, or vibe, translate it to the
   token shape above.
2. **Write `DESIGN.md`** in their project root using `write_file`. Always
','skills\creative\design-md\SKILL.md','95edf35d5b4ec7d8adb57004e28e833bf6855cffb1b9b8f336d7bb6f08ee303f','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:excalidraw:creative','project_skill','skill://simplicio-runtime/excalidraw','skill: excalidraw','---
name: excalidraw
description: "Hand-drawn Excalidraw JSON diagrams (arch, flow, seq)."
version: 1.0.0
author: Hermes Agent
license: MIT
dependencies: []
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Excalidraw, Diagrams, Flowcharts, Architecture, Visualization, JSON]
    related_skills: []

---

# Excalidraw Diagram Skill

Create diagrams by writing standard Excalidraw element JSON and saving as `.excalidraw` files. These files can be drag-and-dropped onto [excalidraw.com](https://excalidraw.com) for viewing and editing. No accounts, no API keys, no rendering libraries -- just JSON.

## When to use

Generate `.excalidraw` files for architecture diagrams, flowcharts, sequence diagrams, concept maps, and more. Files can be opened at excalidraw.com or uploaded for shareable links.

## Workflow

1. **Load this skill** (you already did)
2. **Write the elements JSON** -- an array of Excalidraw element objects
3. **Save the file** using `write_file` to create a `.excalidraw` file
4. **Optionally upload** for a shareable link using `scripts/upload.py` via `terminal`

### Saving a Diagram

Wrap your elements array in the standard `.excalidraw` envelope and save with `write_file`:

```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "hermes-agent",
  "elements": [ ...your elements array here... ],
  "appState": {
    "viewBackgroundColor": "#ffffff"
  }
}
```

Save to any path, e.g. `~/diagrams/my_diagram.excalidraw`.

### Uploading for a Shareable Link

Run the upload script (located in this skill''s `scripts/` directory) via terminal:

```bash
python skills/diagramming/excalidraw/scripts/upload.py ~/diagrams/my_diagram.excalidraw
```

This uploads to excalidraw.com (no account needed) and prints a shareable URL. Requires the `cryptography` pip package (`pip install cryptography`).

---

## Element Format Reference

### Required Fields (all elements)
`type`, `id` (unique string), `x`, `y`, `width`, `height`

### Defaults (skip these -- they''re applied automatically)
- `strokeColor`: `"#1e1e1e"`
- `backgroundColor`: `"transparent"`
- `fillStyle`: `"solid"`
- `strokeWidth`: `2`
- `roughness`: `1` (hand-drawn look)
- `opacity`: `100`

Canvas background is white.

### Element Types

**Rectangle**:
```json
{ "type": "rectangle", "id": "r1", "x": 100, "y": 100, "width": 200, "height": 100 }
```
- `roundness: { "type": 3 }` for rounded corners
- `backgroundColor: "#a5d8ff"`, `fillStyle: "solid"` for filled

**Ellipse**:
```json
{ "type": "ellipse", "id": "e1", "x": 100, "y": 100, "width": 150, "height": 150 }
```

**Diamond**:
```json
{ "type": "diamond", "id": "d1", "x": 100, "y": 100, "width": 150, "height": 150 }
```

**Labeled shape (container binding)** -- create a text element bound to the shape:

> **WARNING:** Do NOT use `"label": { "text": "..." }` on shapes. This is NOT a valid
> Excalidraw property and will be silently ignored, producing blank shapes. You MUST
> use the container binding approach below.

The shape needs `boundElements` listing the text, and the text needs `containerId` pointing back:
```json
{ "type": "rectangle", "id": "r1", "x": 100, "y": 100, "width": 200, "height": 80,
  "roundness": { "type": 3 }, "backgroundColor": "#a5d8ff", "fillStyle": "solid",
  "boundElements": [{ "id": "t_r1", "type": "text" }] },
{ "type": "text", "id": "t_r1", "x": 105, "y": 110, "width": 190, "height": 25,
  "text": "Hello", "fontSize": 20, "fontFamily": 1, "strokeColor": "#1e1e1e",
  "textAlign": "center", "verticalAlign": "middle",
  "containerId": "r1", "originalText": "Hello", "autoResize": true }
```
- Works on rectangle, ellipse, diamond
- Text is auto-centered by Excalidraw when `containerId` is set
- The text `x`/`y`/`width`/`height` are approximate -- Excalidraw recalculates them on load
- `originalText` should match `text`
- Always include `fontFamily: 1` (Virgil/hand-drawn font)

**Labeled arrow** -- same container binding approach:
```json
{ "type": "arrow", "id": "a1", "x": 300, "y": 150, "width": 200, "height": 0,
  "points": [[0,0],[200,0]], "endArrowhead": "arrow",
  "boundElemen','skills\creative\excalidraw\SKILL.md','d7b0fb8b0bc086a5baab82ccbe637eca11e96fb8a14d9aebacd62c312562cb82','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:humanizer:creative','project_skill','skill://simplicio-runtime/humanizer','skill: humanizer','---
name: humanizer
description: "Humanize text: strip AI-isms and add real voice."
version: 2.5.1
author: Siqi Chen (@blader, https://github.com/blader/humanizer), ported by Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [writing, editing, humanize, anti-ai-slop, voice, prose, text]
    category: creative
    homepage: https://github.com/blader/humanizer
    related_skills: [songwriting-and-ai-music]
---

# Humanizer: Remove AI Writing Patterns

Identify and remove signs of AI-generated text to make writing sound natural and human. Based on Wikipedia''s "Signs of AI writing" guide (maintained by WikiProject AI Cleanup), derived from observations of thousands of AI-generated text instances.

**Key insight:** LLMs use statistical algorithms to guess what should come next. The result tends toward the most statistically likely completion, which is how the telltale patterns below get baked in.

## When to use this skill

Load this skill whenever the user asks to:
- "humanize", "de-AI", "de-slop", or "un-ChatGPT" a piece of text
- rewrite something so it doesn''t sound like it was written by an LLM
- edit a draft (blog post, essay, PR description, docs, memo, email, tweet, resume bullet) to sound more natural
- match their voice in writing they''re producing
- review text for AI tells before publishing

Also apply this skill to **your own** output when writing user-facing prose — release notes, PR descriptions, documentation, long-form explanations, summaries. Hermes''s baseline voice already strips most of these, but a focused pass catches what slips through.

## How to use it in Hermes

The text usually arrives one of three ways:
1. **Inline** — user pastes the text directly into the message. Work on it in-place, reply with the rewrite.
2. **File** — user points at a file. Use `read_file` to load it, then `patch` or `write_file` to apply edits. For markdown docs in a repo, a targeted `patch` per section is cleaner than rewriting the whole file.
3. **Voice calibration sample** — user provides an additional sample of their own writing (inline or by file path) and asks you to match it. Read the sample first, then rewrite. See the Voice Calibration section below.

Always show the rewrite to the user. For file edits, show a diff or the changed section — don''t silently overwrite.

## Your task

When given text to humanize:

1. **Identify AI patterns** — scan for the 29 patterns listed below.
2. **Rewrite problematic sections** — replace AI-isms with natural alternatives.
3. **Preserve meaning** — keep the core message intact.
4. **Maintain voice** — match the intended tone (formal, casual, technical, etc.). If a voice sample was provided, match it specifically.
5. **Add soul** — don''t just remove bad patterns, inject actual personality. See PERSONALITY AND SOUL below.
6. **Do a final anti-AI pass** — ask yourself: "What makes the below so obviously AI generated?" Answer briefly with any remaining tells, then revise one more time.


## Voice Calibration (optional)

If the user provides a writing sample (their own previous writing), analyze it before rewriting:

1. **Read the sample first.** Note:
   - Sentence length patterns (short and punchy? Long and flowing? Mixed?)
   - Word choice level (casual? academic? somewhere between?)
   - How they start paragraphs (jump right in? Set context first?)
   - Punctuation habits (lots of dashes? Parenthetical asides? Semicolons?)
   - Any recurring phrases or verbal tics
   - How they handle transitions (explicit connectors? Just start the next point?)

2. **Match their voice in the rewrite.** Don''t just remove AI patterns — replace them with patterns from the sample. If they write short sentences, don''t produce long ones. If they use "stuff" and "things," don''t upgrade to "elements" and "components."

3. **When no sample is provided,** fall back to the default behavior (natural, varied, opinionated voice from the PERSONALITY AND SOUL section below).

### How to provide a sample
- Inline: "Humanize this text. Here''s a sample of my writing for voice m','skills\creative\humanizer\SKILL.md','60b419af3f767c4f20ab24fbce48723562e7efd178af230ee7549ca38a6603ae','skill,simplicio,content',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:hyperframes:creative','project_skill','skill://simplicio-runtime/hyperframes','skill: hyperframes','---
name: hyperframes
description: Create HTML-based video compositions, animated title cards, social overlays, captioned talking-head videos, audio-reactive visuals, and shader transitions using HyperFrames. HTML is the source of truth for video. Use when the user wants a rendered MP4/WebM from an HTML composition, wants to animate text/logos/charts over media, needs captions synced to audio, wants TTS narration, or wants to convert a website into a video.
version: 1.0.0
author: heygen-com
license: Apache-2.0
platforms: [linux, macos, windows]
prerequisites:
  commands: [node, ffmpeg, npx]
metadata:
  hermes:
    tags: [creative, video, animation, html, gsap, motion-graphics]
    related_skills: [manim-video, meme-generation]
    category: creative
    requires_toolsets: [terminal]
---

# HyperFrames

HTML is the source of truth for video. A composition is an HTML file with `data-*` attributes for timing, a GSAP timeline for animation, and CSS for appearance. The HyperFrames engine captures the page frame-by-frame and encodes to MP4/WebM with FFmpeg.

**Complement to `manim-video`:** Use `manim-video` for mathematical/geometric explainers (equations, 3B1B-style). Use `hyperframes` for motion-graphics, talking-head with captions, product tours, social overlays, shader transitions, and anything driven by real video/audio media.

## When to Use

- User asks for a rendered video from text, a script, or a website
- Animated title cards, lower thirds, or typographic intros
- Captioned narration video (TTS + captions synced to waveform)
- Audio-reactive visuals (beat sync, spectrum bars, pulsing glow)
- Scene-to-scene transitions (crossfade, wipe, shader warp, flash-through-white)
- Social overlays (Instagram/TikTok/YouTube style)
- Website-to-video pipeline (capture a URL, produce a promo)
- Any HTML/CSS/JS animation that must render deterministically to a video file

Do **not** use this skill for:
- Pure math/equation animation (→ `manim-video`)
- Image generation or memes (→ `meme-generation`, image models)
- Live video conferencing or streaming

## Quick Reference

```bash
npx hyperframes init my-video               # scaffold a project
cd my-video
npx hyperframes lint                        # validate before preview/render
npx hyperframes preview                     # live-reload browser preview (port 3002)
npx hyperframes render --output final.mp4   # render to MP4
npx hyperframes doctor                      # diagnose environment issues
```

Render flags: `--quality draft|standard|high` · `--fps 24|30|60` · `--format mp4|webm` · `--docker` (reproducible) · `--strict`.

Full CLI reference: [references/cli.md](references/cli.md).

## Setup (one-time)

```bash
bash "$(dirname "$(find ~/.hermes/skills -path ''*/hyperframes/SKILL.md'' 2>/dev/null | head -1)")/scripts/setup.sh"
```

The script:
1. Verifies Node.js >= 22 and FFmpeg are installed (prints fix instructions if not).
2. Installs the `hyperframes` CLI globally (`npm install -g hyperframes@>=0.4.2`).
3. Pre-caches `chrome-headless-shell` via Puppeteer — **required** for best-quality rendering via Chrome''s `HeadlessExperimental.beginFrame` capture path.
4. Runs `npx hyperframes doctor` and reports the result.

See [references/troubleshooting.md](references/troubleshooting.md) if setup fails.

## Procedure

### 1. Plan before writing HTML

Before touching code, articulate at a high level:
- **What** — narrative arc, key moments, emotional beats
- **Structure** — compositions, tracks (video/audio/overlays), durations
- **Visual identity** — colors, fonts, motion character (explosive / cinematic / fluid / technical)
- **Hero frame** — for each scene, the moment when the most elements are simultaneously visible. This is the static layout you''ll build first.

**Visual Identity Gate (HARD-GATE).** Before writing ANY composition HTML, a visual identity must be defined. Do NOT write compositions with default or generic colors (`#333`, `#3b82f6`, `Roboto` are tells that this step was skipped). Check in order:

1. **`DESIGN.md` at project root?** → Use its exact colors, fonts, mo','skills\creative\hyperframes\SKILL.md','e8b25f40abdd4e24bfa43bfd262eef51f6608a593c1d40d80200c128fbcafc59','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:kanban-video-orchestrator:creative','project_skill','skill://simplicio-runtime/kanban-video-orchestrator','skill: kanban-video-orchestrator','---
name: kanban-video-orchestrator
description: Plan, set up, and monitor a multi-agent video production pipeline backed by Hermes Kanban. Use when the user wants to make ANY video — narrative film, product/marketing, music video, explainer, ASCII/terminal art, abstract/generative loop, comic, 3D, real-time/installation — and the work warrants decomposition into specialized profiles (writer, designer, animator, renderer, voice, editor, etc.) coordinated through a kanban board. Performs adaptive discovery to scope the brief, designs an appropriate team for the requested style, generates the setup script that creates Hermes profiles + initial kanban task, then helps monitor execution and intervene when tasks stall or fail. Routes scenes to whichever Hermes rendering / audio / design skill fits each beat (`ascii-video`, `manim-video`, `p5js`, `comfyui`, `touchdesigner-mcp`, `blender-mcp`, `pixel-art`, `baoyu-comic`, `claude-design`, `excalidraw`, `songsee`, `heartmula`, …) plus external APIs for TTS, image-gen, and image-to-video as needed.
version: 1.0.0
author: [SHL0MS, alt-glitch]
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [video, kanban, multi-agent, orchestration, production-pipeline]
    related_skills: [kanban-orchestrator, kanban-worker, ascii-video, manim-video, p5js, comfyui, touchdesigner-mcp, blender-mcp, pixel-art, ascii-art, songwriting-and-ai-music, heartmula, songsee, spotify, youtube-content, claude-design, excalidraw, architecture-diagram, concept-diagrams, baoyu-comic, baoyu-infographic, humanizer, gif-search, meme-generation]
    credits: |
      The single-project workspace layout, profile-config patching pattern,
      SOUL.md-per-profile model, TEAM.md task-graph convention, and
      `--workspace dir:<path>` discipline are adapted from alt-glitch''s
      original multi-agent video pipeline at
      https://github.com/NousResearch/kanban-video-pipeline.
---

# Kanban Video Orchestrator

Wrap any video request — from a 15-second product teaser to a 5-minute narrative
short to a music video to an ASCII loop — in a Hermes Kanban pipeline that
decomposes the work to specialized agent profiles.

This skill does **not** render anything itself. It is a meta-pipeline that:

1. **Scopes** the request through targeted discovery
2. **Designs** an appropriate team (which roles, which tools per role) based on the style
3. **Generates** a setup script that creates Hermes profiles, project workspace, and the initial kanban task
4. **Hands off** to the director profile, which decomposes via the kanban
5. **Monitors** execution, helps intervene when tasks stall or fail

The actual rendering happens inside the kanban once it''s running, via whichever
existing skills + tools fit the scenes — `ascii-video`, `manim-video`, `p5js`,
`comfyui`, `touchdesigner-mcp`, `blender-mcp`, `songwriting-and-ai-music`,
`heartmula`, external APIs, or plain Python with PIL + ffmpeg.

## When NOT to use this skill

- The video is one continuous procedural project that needs no specialists. Just write the code directly.
- The user wants a quick one-shot conversion (e.g. "convert this mp4 to a GIF") — use ffmpeg directly.
- The output is a static image, GIF, or audio-only artifact — use the matching specific skill (`ascii-art`, `gifs`, `meme-generation`, `songwriting-and-ai-music`).
- The work fits a single existing skill cleanly (e.g. a pure ASCII video — just use `ascii-video`).

## Workflow

```
DISCOVER  →  BRIEF  →  TEAM DESIGN  →  SETUP  →  EXECUTE  →  MONITOR
```

### Step 1 — Discover (ask the right questions)

The discovery process is **adaptive**: ask only what is actually needed. Always
start with three questions to identify the broad shape:

- **What is the video?** (one-sentence brief)
- **How long?** (5-30s teaser / 30-90s short / 90s-3min explainer / 3-10min film / longer)
- **What aspect ratio + target platform?** (1:1 / 9:16 / 16:9; X, IG, YouTube, internal, etc.)

From the answer, classify the style category. The style determines which
follow-up questions to ask. **Do not ask all questions','skills\creative\kanban-video-orchestrator\SKILL.md','ec60f6bdd2183af02f511dc19b486c8df7d0840c384178d340ddde602c5cfbd6','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:manim-video:creative','project_skill','skill://simplicio-runtime/manim-video','skill: manim-video','---
name: manim-video
description: "Manim CE animations: 3Blue1Brown math/algo videos."
version: 1.0.0
platforms: [linux, macos, windows]
---

# Manim Video Production Pipeline

## When to use

Use when users request: animated explanations, math animations, concept visualizations, algorithm walkthroughs, technical explainers, 3Blue1Brown style videos, or any programmatic animation with geometric/mathematical content. Creates 3Blue1Brown-style explainer videos, algorithm visualizations, equation derivations, architecture diagrams, and data stories using Manim Community Edition.

## Creative Standard

This is educational cinema. Every frame teaches. Every animation reveals structure.

**Before writing a single line of code**, articulate the narrative arc. What misconception does this correct? What is the "aha moment"? What visual story takes the viewer from confusion to understanding? The user''s prompt is a starting point — interpret it with pedagogical ambition.

**Geometry before algebra.** Show the shape first, the equation second. Visual memory encodes faster than symbolic memory. When the viewer sees the geometric pattern before the formula, the equation feels earned.

**First-render excellence is non-negotiable.** The output must be visually clear and aesthetically cohesive without revision rounds. If something looks cluttered, poorly timed, or like "AI-generated slides," it is wrong.

**Opacity layering directs attention.** Never show everything at full brightness. Primary elements at 1.0, contextual elements at 0.4, structural elements (axes, grids) at 0.15. The brain processes visual salience in layers.

**Breathing room.** Every animation needs `self.wait()` after it. The viewer needs time to absorb what just appeared. Never rush from one animation to the next. A 2-second pause after a key reveal is never wasted.

**Cohesive visual language.** All scenes share a color palette, consistent typography sizing, matching animation speeds. A technically correct video where every scene uses random different colors is an aesthetic failure.

## Prerequisites

Run `scripts/setup.sh` to verify all dependencies. Requires: Python 3.10+, Manim Community Edition v0.20+ (`pip install manim`), LaTeX (`texlive-full` on Linux, `mactex` on macOS), and ffmpeg. Reference docs tested against Manim CE v0.20.1.

## Modes

| Mode | Input | Output | Reference |
|------|-------|--------|-----------|
| **Concept explainer** | Topic/concept | Animated explanation with geometric intuition | `references/scene-planning.md` |
| **Equation derivation** | Math expressions | Step-by-step animated proof | `references/equations.md` |
| **Algorithm visualization** | Algorithm description | Step-by-step execution with data structures | `references/graphs-and-data.md` |
| **Data story** | Data/metrics | Animated charts, comparisons, counters | `references/graphs-and-data.md` |
| **Architecture diagram** | System description | Components building up with connections | `references/mobjects.md` |
| **Paper explainer** | Research paper | Key findings and methods animated | `references/scene-planning.md` |
| **3D visualization** | 3D concept | Rotating surfaces, parametric curves, spatial geometry | `references/camera-and-3d.md` |

## Stack

Single Python script per project. No browser, no Node.js, no GPU required.

| Layer | Tool | Purpose |
|-------|------|---------|
| Core | Manim Community Edition | Scene rendering, animation engine |
| Math | LaTeX (texlive/MiKTeX) | Equation rendering via `MathTex` |
| Video I/O | ffmpeg | Scene stitching, format conversion, audio muxing |
| TTS | ElevenLabs / Qwen3-TTS (optional) | Narration voiceover |

## Pipeline

```
PLAN --> CODE --> RENDER --> STITCH --> AUDIO (optional) --> REVIEW
```

1. **PLAN** — Write `plan.md` with narrative arc, scene list, visual elements, color palette, voiceover script
2. **CODE** — Write `script.py` with one class per scene, each independently renderable
3. **RENDER** — `manim -ql script.py Scene1 Scene2 ...` for draft, `-qh` for production
4. **STITCH** — ffmpeg concat of scene clips i','skills\creative\manim-video\SKILL.md','46d68d8d8633383e2d5c5f4895666791dddeef324839f94b53b963e26b315959','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:meme-generation:creative','project_skill','skill://simplicio-runtime/meme-generation','skill: meme-generation','---
name: meme-generation
description: Generate real meme images by picking a template and overlaying text with Pillow. Produces actual .png meme files.
version: 2.0.0
author: adanaleycio
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [creative, memes, humor, images]
    related_skills: [ascii-art, generative-widgets]
    category: creative
---

# Meme Generation

Generate actual meme images from a topic. Picks a template, writes captions, and renders a real .png file with text overlay.

## When to Use

- User asks you to make or generate a meme
- User wants a meme about a specific topic, situation, or frustration
- User says "meme this" or similar

## Available Templates

The script supports **any of the ~100 popular imgflip templates** by name or ID, plus 10 curated templates with hand-tuned text positioning.

### Curated Templates (custom text placement)

| ID | Name | Fields | Best for |
|----|------|--------|----------|
| `this-is-fine` | This is Fine | top, bottom | chaos, denial |
| `drake` | Drake Hotline Bling | reject, approve | rejecting/preferring |
| `distracted-boyfriend` | Distracted Boyfriend | distraction, current, person | temptation, shifting priorities |
| `two-buttons` | Two Buttons | left, right, person | impossible choice |
| `expanding-brain` | Expanding Brain | 4 levels | escalating irony |
| `change-my-mind` | Change My Mind | statement | hot takes |
| `woman-yelling-at-cat` | Woman Yelling at Cat | woman, cat | arguments |
| `one-does-not-simply` | One Does Not Simply | top, bottom | deceptively hard things |
| `grus-plan` | Gru''s Plan | step1-3, realization | plans that backfire |
| `batman-slapping-robin` | Batman Slapping Robin | robin, batman | shutting down bad ideas |

### Dynamic Templates (from imgflip API)

Any template not in the curated list can be used by name or imgflip ID. These get smart default text positioning (top/bottom for 2-field, evenly spaced for 3+). Search with:
```bash
python "$SKILL_DIR/scripts/generate_meme.py" --search "disaster"
```

## Procedure

### Mode 1: Classic Template (default)

1. Read the user''s topic and identify the core dynamic (chaos, dilemma, preference, irony, etc.)
2. Pick the template that best matches. Use the "Best for" column, or search with `--search`.
3. Write short captions for each field (8-12 words max per field, shorter is better).
4. Find the skill''s script directory:
   ```
   SKILL_DIR=$(dirname "$(find ~/.hermes/skills -path ''*/meme-generation/SKILL.md'' 2>/dev/null | head -1)")
   ```
5. Run the generator:
   ```bash
   python "$SKILL_DIR/scripts/generate_meme.py" <template_id> /tmp/meme.png "caption 1" "caption 2" ...
   ```
6. Return the image with `MEDIA:/tmp/meme.png`

### Mode 2: Custom AI Image (when image_generate is available)

Use this when no classic template fits, or when the user wants something original.

1. Write the captions first.
2. Use `image_generate` to create a scene that matches the meme concept. Do NOT include any text in the image prompt — text will be added by the script. Describe only the visual scene.
3. Find the generated image path from the image_generate result URL. Download it to a local path if needed.
4. Run the script with `--image` to overlay text, choosing a mode:
   - **Overlay** (text directly on image, white with black outline):
     ```bash
     python "$SKILL_DIR/scripts/generate_meme.py" --image /path/to/scene.png /tmp/meme.png "top text" "bottom text"
     ```
   - **Bars** (black bars above/below with white text — cleaner, always readable):
     ```bash
     python "$SKILL_DIR/scripts/generate_meme.py" --image /path/to/scene.png --bars /tmp/meme.png "top text" "bottom text"
     ```
   Use `--bars` when the image is busy/detailed and text would be hard to read on top of it.
5. **Verify with vision** (if `vision_analyze` is available): Check the result looks good:
   ```
   vision_analyze(image_url="/tmp/meme.png", question="Is the text legible and well-positioned? Does the meme work visually?")
   ```
   If the vision model flags issues (text hard to read, bad ','skills\creative\meme-generation\SKILL.md','0e2487dc0bfa09c24c2862aa73004237ec2f0c2131f87e03f8155bca774870ba','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:p5js:creative','project_skill','skill://simplicio-runtime/p5js','skill: p5js','---
name: p5js
description: "p5.js sketches: gen art, shaders, interactive, 3D."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [creative-coding, generative-art, p5js, canvas, interactive, visualization, webgl, shaders, animation]
    related_skills: [ascii-video, manim-video, excalidraw]
---

# p5.js Production Pipeline

## When to use

Use when users request: p5.js sketches, creative coding, generative art, interactive visualizations, canvas animations, browser-based visual art, data viz, shader effects, or any p5.js project.

## What''s inside

Production pipeline for interactive and generative visual art using p5.js. Creates browser-based sketches, generative art, data visualizations, interactive experiences, 3D scenes, audio-reactive visuals, and motion graphics — exported as HTML, PNG, GIF, MP4, or SVG. Covers: 2D/3D rendering, noise and particle systems, flow fields, shaders (GLSL), pixel manipulation, kinetic typography, WebGL scenes, audio analysis, mouse/keyboard interaction, and headless high-res export.

## Creative Standard

This is visual art rendered in the browser. The canvas is the medium; the algorithm is the brush.

**Before writing a single line of code**, articulate the creative concept. What does this piece communicate? What makes the viewer stop scrolling? What separates this from a code tutorial example? The user''s prompt is a starting point — interpret it with creative ambition.

**First-render excellence is non-negotiable.** The output must be visually striking on first load. If it looks like a p5.js tutorial exercise, a default configuration, or "AI-generated creative coding," it is wrong. Rethink before shipping.

**Go beyond the reference vocabulary.** The noise functions, particle systems, color palettes, and shader effects in the references are a starting vocabulary. For every project, combine, layer, and invent. The catalog is a palette of paints — you write the painting.

**Be proactively creative.** If the user asks for "a particle system," deliver a particle system with emergent flocking behavior, trailing ghost echoes, palette-shifted depth fog, and a background noise field that breathes. Include at least one visual detail the user didn''t ask for but will appreciate.

**Dense, layered, considered.** Every frame should reward viewing. Never flat white backgrounds. Always compositional hierarchy. Always intentional color. Always micro-detail that only appears on close inspection.

**Cohesive aesthetic over feature count.** All elements must serve a unified visual language — shared color temperature, consistent stroke weight vocabulary, harmonious motion speeds. A sketch with ten unrelated effects is worse than one with three that belong together.

## Modes

| Mode | Input | Output | Reference |
|------|-------|--------|-----------|
| **Generative art** | Seed / parameters | Procedural visual composition (still or animated) | `references/visual-effects.md` |
| **Data visualization** | Dataset / API | Interactive charts, graphs, custom data displays | `references/interaction.md` |
| **Interactive experience** | None (user drives) | Mouse/keyboard/touch-driven sketch | `references/interaction.md` |
| **Animation / motion graphics** | Timeline / storyboard | Timed sequences, kinetic typography, transitions | `references/animation.md` |
| **3D scene** | Concept description | WebGL geometry, lighting, camera, materials | `references/webgl-and-3d.md` |
| **Image processing** | Image file(s) | Pixel manipulation, filters, mosaic, pointillism | `references/visual-effects.md` § Pixel Manipulation |
| **Audio-reactive** | Audio file / mic | Sound-driven generative visuals | `references/interaction.md` § Audio Input |

## Stack

Single self-contained HTML file per project. No build step required.

| Layer | Tool | Purpose |
|-------|------|---------|
| Core | p5.js 1.11.3 (CDN) | Canvas rendering, math, transforms, event handling |
| 3D | p5.js WebGL mode | 3D geometry, camera, lighting, GLSL shaders |
| Audio | p5.sound.js (CDN) | FFT analysis, amplitude, mic input, ','skills\creative\p5js\SKILL.md','8c65e7403f299b0b89921c1d2d75549c6b0ac21d2b9acac34fb2ed3ef16ebc3a','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pixel-art:creative','project_skill','skill://simplicio-runtime/pixel-art','skill: pixel-art','---
name: pixel-art
description: "Pixel art w/ era palettes (NES, Game Boy, PICO-8)."
version: 2.0.0
author: dodo-reach
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [creative, pixel-art, arcade, snes, nes, gameboy, retro, image, video]
    category: creative
    credits:
      - "Hardware palettes and animation loops ported from Synero/pixel-art-studio (MIT) — https://github.com/Synero/pixel-art-studio"
---

# Pixel Art

Convert any image into retro pixel art, then optionally animate it into a short
MP4 or GIF with era-appropriate effects (rain, fireflies, snow, embers).

Two scripts ship with this skill:

- `scripts/pixel_art.py` — photo → pixel-art PNG (Floyd-Steinberg dithering)
- `scripts/pixel_art_video.py` — pixel-art PNG → animated MP4 (+ optional GIF)

Each is importable or runnable directly. Presets snap to hardware palettes
when you want era-accurate colors (NES, Game Boy, PICO-8, etc.), or use
adaptive N-color quantization for arcade/SNES-style looks.

## When to Use

- User wants retro pixel art from a source image
- User asks for NES / Game Boy / PICO-8 / C64 / arcade / SNES styling
- User wants a short looping animation (rain scene, night sky, snow, etc.)
- Posters, album covers, social posts, sprites, characters, avatars

## Workflow

Before generating, confirm the style with the user. Different presets produce
very different outputs and regenerating is costly.

### Step 1 — Offer a style

Call `clarify` with 4 representative presets. Pick the set based on what the
user asked for — don''t just dump all 14.

Default menu when the user''s intent is unclear:

```python
clarify(
    question="Which pixel-art style do you want?",
    choices=[
        "arcade — bold, chunky 80s cabinet feel (16 colors, 8px)",
        "nes — Nintendo 8-bit hardware palette (54 colors, 8px)",
        "gameboy — 4-shade green Game Boy DMG",
        "snes — cleaner 16-bit look (32 colors, 4px)",
    ],
)
```

When the user already named an era (e.g. "80s arcade", "Gameboy"), skip
`clarify` and use the matching preset directly.

### Step 2 — Offer animation (optional)

If the user asked for a video/GIF, or the output might benefit from motion,
ask which scene:

```python
clarify(
    question="Want to animate it? Pick a scene or skip.",
    choices=[
        "night — stars + fireflies + leaves",
        "urban — rain + neon pulse",
        "snow — falling snowflakes",
        "skip — just the image",
    ],
)
```

Do NOT call `clarify` more than twice in a row. One for style, one for scene if
animation is on the table. If the user explicitly asked for a specific style
and scene in their message, skip `clarify` entirely.

### Step 3 — Generate

Run `pixel_art()` first; if animation was requested, chain into
`pixel_art_video()` on the result.

## Preset Catalog

| Preset | Era | Palette | Block | Best for |
|--------|-----|---------|-------|----------|
| `arcade` | 80s arcade | adaptive 16 | 8px | Bold posters, hero art |
| `snes` | 16-bit | adaptive 32 | 4px | Characters, detailed scenes |
| `nes` | 8-bit | NES (54) | 8px | True NES look |
| `gameboy` | DMG handheld | 4 green shades | 8px | Monochrome Game Boy |
| `gameboy_pocket` | Pocket handheld | 4 grey shades | 8px | Mono GB Pocket |
| `pico8` | PICO-8 | 16 fixed | 6px | Fantasy-console look |
| `c64` | Commodore 64 | 16 fixed | 8px | 8-bit home computer |
| `apple2` | Apple II hi-res | 6 fixed | 10px | Extreme retro, 6 colors |
| `teletext` | BBC Teletext | 8 pure | 10px | Chunky primary colors |
| `mspaint` | Windows MS Paint | 24 fixed | 8px | Nostalgic desktop |
| `mono_green` | CRT phosphor | 2 green | 6px | Terminal/CRT aesthetic |
| `mono_amber` | CRT amber | 2 amber | 6px | Amber monitor look |
| `neon` | Cyberpunk | 10 neons | 6px | Vaporwave/cyber |
| `pastel` | Soft pastel | 10 pastels | 6px | Kawaii / gentle |

Named palettes live in `scripts/palettes.py` (see `references/palettes.md` for
the complete list — 28 named palettes total). Any preset can be overridden:

```python
pixel_art("in.png", "out.png", preset="snes", palette="PICO_8",','skills\creative\pixel-art\SKILL.md','8163d0d8d1d97115ed90d6ea405210dbbcc15bab92360b63076fbc88d6d78fa1','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:popular-web-designs:creative','project_skill','skill://simplicio-runtime/popular-web-designs','skill: popular-web-designs','---
name: popular-web-designs
description: 54 real design systems (Stripe, Linear, Vercel) as HTML/CSS.
version: 1.0.0
author: Hermes Agent + Teknium (design systems sourced from VoltAgent/awesome-design-md)
license: MIT
tags: [design, css, html, ui, web-development, design-systems, templates]
platforms: [linux, macos, windows]
triggers:
  - build a page that looks like
  - make it look like stripe
  - design like linear
  - vercel style
  - create a UI
  - web design
  - landing page
  - dashboard design
  - website styled like
---

# Popular Web Designs

54 real-world design systems ready for use when generating HTML/CSS. Each template captures a
site''s complete visual language: color palette, typography hierarchy, component styles, spacing
system, shadows, responsive behavior, and practical agent prompts with exact CSS values.

## Related design skills

- **`claude-design`** — use for the design *process and taste* (scoping a brief,
  producing variants, verifying a local HTML artifact, avoiding AI-design slop).
  Pair it with this skill when the user wants a thoughtfully-designed page styled
  after a known brand: `claude-design` drives the workflow, this skill supplies
  the visual vocabulary.
- **`design-md`** — use when the deliverable is a formal DESIGN.md token spec
  file, not a rendered artifact.

## How to Use

1. Pick a design from the catalog below
2. Load it: `skill_view(name="popular-web-designs", file_path="templates/<site>.md")`
3. Use the design tokens and component specs when generating HTML
4. Pair with the `generative-widgets` skill to serve the result via cloudflared tunnel

Each template includes a **Hermes Implementation Notes** block at the top with:
- CDN font substitute and Google Fonts `<link>` tag (ready to paste)
- CSS font-family stacks for primary and monospace
- Reminders to use `write_file` for HTML creation and `browser_vision` for verification

## HTML Generation Pattern

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Page Title</title>
  <!-- Paste the Google Fonts <link> from the template''s Hermes notes -->
  <link href="https://fonts.googleapis.com/css2?family=..." rel="stylesheet">
  <style>
    /* Apply the template''s color palette as CSS custom properties */
    :root {
      --color-bg: #ffffff;
      --color-text: #171717;
      --color-accent: #533afd;
      /* ... more from template Section 2 */
    }
    /* Apply typography from template Section 3 */
    body {
      font-family: ''Inter'', system-ui, sans-serif;
      color: var(--color-text);
      background: var(--color-bg);
    }
    /* Apply component styles from template Section 4 */
    /* Apply layout from template Section 5 */
    /* Apply shadows from template Section 6 */
  </style>
</head>
<body>
  <!-- Build using component specs from the template -->
</body>
</html>
```

Write the file with `write_file`, serve with the `generative-widgets` workflow (cloudflared tunnel),
and verify the result with `browser_vision` to confirm visual accuracy.

## Font Substitution Reference

Most sites use proprietary fonts unavailable via CDN. Each template maps to a Google Fonts
substitute that preserves the design''s character. Common mappings:

| Proprietary Font | CDN Substitute | Character |
|---|---|---|
| Geist / Geist Sans | Geist (on Google Fonts) | Geometric, compressed tracking |
| Geist Mono | Geist Mono (on Google Fonts) | Clean monospace, ligatures |
| sohne-var (Stripe) | Source Sans 3 | Light weight elegance |
| Berkeley Mono | JetBrains Mono | Technical monospace |
| Airbnb Cereal VF | DM Sans | Rounded, friendly geometric |
| Circular (Spotify) | DM Sans | Geometric, warm |
| figmaSans | Inter | Clean humanist |
| Pin Sans (Pinterest) | DM Sans | Friendly, rounded |
| NVIDIA-EMEA | Inter (or Arial system) | Industrial, clean |
| CoinbaseDisplay/Sans | DM Sans | Geometric, trustworthy |
| UberMove | DM Sans | Bold, tight |
| HashiCorp Sans | Inter | Enterprise, neutral |
| waldenburgNormal (Sanity) | Space ','skills\creative\popular-web-designs\SKILL.md','d46b48297047a888d11c9ee7a4f3b6f70ea60dc776f7306cd41609bece840288','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pretext:creative','project_skill','skill://simplicio-runtime/pretext','skill: pretext','---
name: pretext
description: "Use when building creative browser demos with @chenglou/pretext — DOM-free text layout for ASCII art, typographic flow around obstacles, text-as-geometry games, kinetic typography, and text-powered generative art. Produces single-file HTML demos by default."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [creative-coding, typography, pretext, ascii-art, canvas, generative, text-layout, kinetic-typography]
    related_skills: [p5js, claude-design, excalidraw, architecture-diagram]
---

# Pretext Creative Demos

## Overview

[`@chenglou/pretext`](https://github.com/chenglou/pretext) is a 15KB zero-dependency TypeScript library by Cheng Lou (React core, ReasonML, Midjourney) for **DOM-free multiline text measurement and layout**. It does one thing: given `(text, font, width)`, return the line breaks, per-line widths, per-grapheme positions, and total height — all via canvas measurement, no reflow.

That sounds like plumbing. It is not. Because it is fast and geometric, it is a **creative primitive**: you can reflow paragraphs around a moving sprite at 60fps, build games whose level geometry is made of real words, drive ASCII logos through prose, shatter text into particles with exact per-grapheme starting positions, or pack shrink-wrapped multiline UI without any `getBoundingClientRect` thrash.

This skill exists so Hermes can make **cool demos** with it — the kind people post to X. See `pretext.cool` and `chenglou.me/pretext` for the community demo corpus.

## When to Use

Use when the user asks for:
- A "pretext demo" / "cool pretext thing" / "text-as-X"
- Text flowing around a moving shape (hero sections, editorial layouts, animated long-form pages)
- ASCII-art effects using **real words or prose**, not monospace rasters
- Games where the playfield / obstacles / bricks are made of text (Tetris-from-letters, Breakout-of-prose)
- Kinetic typography with per-glyph physics (shatter, scatter, flock, flow)
- Typographic generative art, especially with non-Latin scripts or mixed scripts
- Multiline "shrink-wrap" UI (smallest container width that still fits the text)
- Anything that would require knowing line breaks *before* rendering

Don''t use for:
- Static SVG/HTML pages where CSS already solves layout — just use CSS
- Rich text editors, general inline formatting engines (pretext is intentionally narrow)
- Image → text (use `ascii-art` / `ascii-video` skills)
- Pure canvas generative art with no text role — use `p5js`

## Creative Standard

This is visual art rendered in a browser. Pretext returns numbers; **you** draw the thing.

- **Don''t ship a "hello world" demo.** The `hello-orb-flow.html` template is the *starting* point. Every delivered demo must add intentional color, motion, composition, and one visual detail the user didn''t ask for but will appreciate.
- **Dark backgrounds, warm cores, considered palette.** Classic amber-on-black (CRT / terminal) works, but so do cold-white-on-charcoal (editorial) and desaturated pastels (risograph). Pick one and commit.
- **Proportional fonts are the point.** Pretext''s whole vibe is "not monospaced" — lean into it. Use Iowan Old Style, Inter, JetBrains Mono, Helvetica Neue, or a variable font. Never default sans.
- **Real source/text, not lorem ipsum.** The corpus should mean something. Short manifestos, poetry, real source code, a found text, the library''s own README — never `lorem ipsum`.
- **First-paint excellence.** No loading states, no blank frames. The demo must look shippable the instant it opens.

## Stack

Single self-contained HTML file per demo. No build step.

| Layer | Tool | Purpose |
|-------|------|---------|
| Core | `@chenglou/pretext` via `esm.sh` CDN | Text measurement + line layout |
| Render | HTML5 Canvas 2D | Glyph rendering, per-frame composition |
| Segmentation | `Intl.Segmenter` (built-in) | Grapheme splitting for emoji / CJK / combining marks |
| Interaction | Raw DOM events | Mouse / touch / wheel — no framework |

```html
<script type="module">
import {','skills\creative\pretext\SKILL.md','4e625a31285f98e71957bf09f3fa5ad2b42786f58fafae99322cc09f54014e72','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:sketch:creative','project_skill','skill://simplicio-runtime/sketch','skill: sketch','---
name: sketch
description: "Throwaway HTML mockups: 2-3 design variants to compare."
version: 1.0.0
author: Hermes Agent (adapted from gsd-build/get-shit-done)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [sketch, mockup, design, ui, prototype, html, variants, exploration, wireframe, comparison]
    related_skills: [spike, claude-design, popular-web-designs, excalidraw]
---

# Sketch

Use this skill when the user wants to **see a design direction before committing** to one — exploring a UI/UX idea as disposable HTML mockups. The point is to generate 2-3 interactive variants so the user can compare visual directions side-by-side, not to produce shippable code.

Load this when the user says things like "sketch this screen", "show me what X could look like", "compare layout A vs B", "give me 2-3 takes on this UI", "let me see some variants", "mockup this before I build".

## When NOT to use this

- User wants a production component — use `claude-design` or build it properly
- User wants a polished one-off HTML artifact (landing page, deck) — `claude-design`
- User wants a diagram — `excalidraw`, `architecture-diagram`
- The design is already locked — just build it

## If the user has the full GSD system installed

If `gsd-sketch` shows up as a sibling skill (installed via `npx get-shit-done-cc --hermes`), prefer **`gsd-sketch`** for the full workflow: persistent `.planning/sketches/` with MANIFEST, frontier mode analysis, consistency audits across past sketches, and integration with the rest of GSD. This skill is the lightweight standalone version — one-off sketching without the state machinery.

## Core method

```
intake  →  variants  →  head-to-head  →  pick winner (or iterate)
```

### 1. Intake (skip if the user already gave you enough)

Before generating variants, get three things — one question at a time, not all at once:

1. **Feel.** "What should this feel like? Adjectives, emotions, a vibe." — *"calm, editorial, like Linear"* tells you more than *"minimal"*.
2. **References.** "What apps, sites, or products capture the feel you''re imagining?" — actual references beat abstract descriptions.
3. **Core action.** "What''s the single most important thing a user does on this screen?" — the variants should all serve this well; if they don''t, they''re just decoration.

Reflect each answer briefly before the next question. If the user already gave you all three upfront, skip straight to variants.

### 2. Variants (2-3, never 1, rarely 4+)

Produce **2-3 variants** in one go. Each variant is a complete, standalone HTML file. Don''t describe variants — build them. The point is comparison.

Each variant should take a **different design stance**, not different pixel values. Three good variant axes:

- **Density:** compact / airy / ultra-dense (pick two contrasting poles)
- **Emphasis:** content-first / action-first / tool-first
- **Aesthetic:** editorial / utilitarian / playful
- **Layout:** single-column / sidebar / split-pane
- **Grounding:** card-based / bare-content / document-style

Pick one axis and pull apart from it. Two variants that differ only in accent color are wasted effort — the user can''t distinguish them.

**Variant naming:** describe the stance, not the number.

```
sketches/
├── 001-calm-editorial/
│   ├── index.html
│   └── README.md
├── 001-utilitarian-dense/
│   ├── index.html
│   └── README.md
└── 001-playful-split/
    ├── index.html
    └── README.md
```

### 3. Make them real HTML

Each variant is a **single self-contained HTML file**:

- Inline `<style>` — no build step, no external CSS
- System fonts or one Google Font via `<link>`
- Tailwind via CDN (`<script src="https://cdn.tailwindcss.com"></script>`) is fine
- Realistic fake content — actual sentences, actual names, not "Lorem ipsum"
- **Interactive**: links clickable, hovers real, at least one state transition (open/close, filter, toggle). A frozen static image is a worse spike than a sloppy animated one.

Open it in a browser. If it looks broken, fix it before showing the user.

**Verify variants visually — us','skills\creative\sketch\SKILL.md','2edd91f8f2a9c525e20ad2a50791cca1e3f2e87e39644a26de3d09be29f0a826','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:songwriting-and-ai-music:creative','project_skill','skill://simplicio-runtime/songwriting-and-ai-music','skill: songwriting-and-ai-music','---
name: songwriting-and-ai-music
description: "Songwriting craft and Suno AI music prompts."
tags: [songwriting, music, suno, parody, lyrics, creative]
platforms: [linux, macos, windows]
triggers:
  - writing a song
  - song lyrics
  - music prompt
  - suno prompt
  - parody song
  - adapting a song
  - AI music generation
---

# Songwriting & AI Music Generation

Everything here is a GUIDELINE, not a rule. Art breaks rules on purpose.
Use what serves the song. Ignore what doesn''t.

---

## 1. Song Structure (Pick One or Invent Your Own)

Common skeletons — mix, modify, or throw out as needed:

```
ABABCB  Verse/Chorus/Verse/Chorus/Bridge/Chorus    (most pop/rock)
AABA    Verse/Verse/Bridge/Verse (refrain-based)    (jazz standards, ballads)
ABAB    Verse/Chorus alternating                    (simple, direct)
AAA     Verse/Verse/Verse (strophic, no chorus)     (folk, storytelling)
```

The six building blocks:
- Intro      — set the mood, pull the listener in
- Verse      — the story, the details, the world-building
- Pre-Chorus — optional tension ramp before the payoff
- Chorus     — the emotional core, the part people remember
- Bridge     — a detour, a shift in perspective or key
- Outro      — the farewell, can echo or subvert the rest

You don''t need all of these. Some great songs are just one section
that evolves. Structure serves the emotion, not the other way around.

---

## 2. Rhyme, Meter, and Sound

RHYME TYPES (from tight to loose):
- Perfect: lean/mean
- Family: crate/braid
- Assonance: had/glass (same vowels, different endings)
- Consonance: scene/when (different vowels, similar endings)
- Near/slant: enough to suggest connection without locking it down

Mix them. All perfect rhymes can sound like a nursery rhyme.
All slant rhymes can sound lazy. The blend is where it lives.

INTERNAL RHYME: Rhyming within a line, not just at the ends.
  "We pruned the lies from bleeding trees / Distilled the storm
   from entropy" — "lies/flies," "trees/entropy" create internal echoes.

METER: The rhythm of stressed vs unstressed syllables.
- Matching syllable counts between parallel lines helps singability
- The STRESSED syllables matter more than total count
- Say it out loud. If you stumble, the meter needs work.
- Intentionally breaking meter can create emphasis or surprise

---

## 3. Emotional Arc and Dynamics

Think of a song as a journey, not a flat road.

ENERGY MAPPING (rough idea, not prescription):
  Intro: 2-3  |  Verse: 5-6  |  Pre-Chorus: 7
  Chorus: 8-9  |  Bridge: varies  |  Final Chorus: 9-10

The most powerful dynamic trick: CONTRAST.
- Whisper before a scream hits harder than just screaming
- Sparse before dense. Slow before fast. Low before high.
- The drop only works because of the buildup
- Silence is an instrument

"Whisper to roar to whisper" — start intimate, build to full power,
strip back to vulnerability. Works for ballads, epics, anthems.

---

## 4. Writing Lyrics That Work

SHOW, DON''T TELL (usually):
- "I was sad" = flat
- "Your hoodie''s still on the hook by the door" = alive
- But sometimes "I give my life" said plainly IS the power

THE HOOK:
- The line people remember, hum, repeat
- Usually the title or core phrase
- Works best when melody + lyric + emotion all align
- Place it where it lands hardest (often first/last line of chorus)

PROSODY — lyrics and music supporting each other:
- Stable feelings (resolution, peace) pair with settled melodies,
  perfect rhymes, resolved chords
- Unstable feelings (longing, doubt) pair with wandering melodies,
  near-rhymes, unresolved chords
- Verse melody typically sits lower, chorus goes higher
- But flip this if it serves the song

AVOID (unless you''re doing it on purpose):
- Cliches on autopilot ("heart of gold" without earning it)
- Forcing word order to hit a rhyme ("Yoda-speak")
- Same energy in every section (flat dynamics)
- Treating your first draft as sacred — revision is creation

---

## 5. Parody and Adaptation

When rewriting an existing song with new lyrics:

THE SKELETON: Map the original''s structure first.
- Count syllables per l','skills\creative\songwriting-and-ai-music\SKILL.md','c6aa3c5fa40cf10d2eb6e1cc52f5c04e0e1e6058488ff1f855c79e96e1f23b66','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:touchdesigner-mcp:creative','project_skill','skill://simplicio-runtime/touchdesigner-mcp','skill: touchdesigner-mcp','---
name: touchdesigner-mcp
description: "Control a running TouchDesigner instance via twozero MCP — create operators, set parameters, wire connections, execute Python, build real-time visuals. 36 native tools."
version: 1.1.0
author: kshitijk4poor
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [TouchDesigner, MCP, twozero, creative-coding, real-time-visuals, generative-art, audio-reactive, VJ, installation, GLSL]
    related_skills: [native-mcp, ascii-video, manim-video, hermes-video]

---

# TouchDesigner Integration (twozero MCP)

## CRITICAL RULES

1. **NEVER guess parameter names.** Call `td_get_par_info` for the op type FIRST. Your training data is wrong for TD 2025.32.
2. **If `tdAttributeError` fires, STOP.** Call `td_get_operator_info` on the failing node before continuing.
3. **NEVER hardcode absolute paths** in script callbacks. Use `me.parent()` / `scriptOp.parent()`.
4. **Prefer native MCP tools over td_execute_python.** Use `td_create_operator`, `td_set_operator_pars`, `td_get_errors` etc. Only fall back to `td_execute_python` for complex multi-step logic.
5. **Call `td_get_hints` before building.** It returns patterns specific to the op type you''re working with.

## Architecture

```
Hermes Agent -> MCP (Streamable HTTP) -> twozero.tox (port 40404) -> TD Python
```

36 native tools. Free plugin (no payment/license — confirmed April 2026).
Context-aware (knows selected OP, current network).
Hub health check: `GET http://localhost:40404/mcp` returns JSON with instance PID, project name, TD version.

## Setup (Automated)

Run the setup script to handle everything:

```bash
bash "${HERMES_HOME:-$HOME/.hermes}/skills/creative/touchdesigner-mcp/scripts/setup.sh"
```

The script will:
1. Check if TD is running
2. Download twozero.tox if not already cached
3. Add `twozero_td` MCP server to Hermes config (if missing)
4. Test the MCP connection on port 40404
5. Report what manual steps remain (drag .tox into TD, enable MCP toggle)

### Manual steps (one-time, cannot be automated)

1. **Drag `~/Downloads/twozero.tox` into the TD network editor** → click Install
2. **Enable MCP:** click twozero icon → Settings → mcp → "auto start MCP" → Yes
3. **Restart Hermes session** to pick up the new MCP server

After setup, verify:
```bash
nc -z 127.0.0.1 40404 && echo "twozero MCP: READY"
```

## Environment Notes

- **Non-Commercial TD** caps resolution at 1280×1280. Use `outputresolution = ''custom''` and set width/height explicitly.
- **Codecs:** `prores` (preferred on macOS) or `mjpa` as fallback. H.264/H.265/AV1 require a Commercial license.
- Always call `td_get_par_info` before setting params — names vary by TD version (see CRITICAL RULES #1).

## Workflow

### Step 0: Discover (before building anything)

```
Call td_get_par_info with op_type for each type you plan to use.
Call td_get_hints with the topic you''re building (e.g. "glsl", "audio reactive", "feedback").
Call td_get_focus to see where the user is and what''s selected.
Call td_get_network to see what already exists.
```

No temp nodes, no cleanup. This replaces the old discovery dance entirely.

### Step 1: Clean + Build

**IMPORTANT: Split cleanup and creation into SEPARATE MCP calls.** Destroying and recreating same-named nodes in one `td_execute_python` script causes "Invalid OP object" errors. See pitfalls #11b.

Use `td_create_operator` for each node (handles viewport positioning automatically):

```
td_create_operator(type="noiseTOP", parent="/project1", name="bg", parameters={"resolutionw": 1280, "resolutionh": 720})
td_create_operator(type="levelTOP", parent="/project1", name="brightness")
td_create_operator(type="nullTOP", parent="/project1", name="out")
```

For bulk creation or wiring, use `td_execute_python`:

```python
# td_execute_python script:
root = op(''/project1'')
nodes = []
for name, optype in [(''bg'', noiseTOP), (''fx'', levelTOP), (''out'', nullTOP)]:
    n = root.create(optype, name)
    nodes.append(n.path)
# Wire chain
for i in range(len(nodes)-1):
    op(nodes[i]).outputConnectors[0].connect(op(nodes[i+1]).inputCo','skills\creative\touchdesigner-mcp\SKILL.md','1b933bd1121eba57cb0f699ec221ea489c02d6e4d76e18d53bbcc080fda02de3','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:unreal-engine-mcp:creative','project_skill','skill://simplicio-runtime/unreal-engine-mcp','skill: unreal-engine-mcp','---
name: unreal-engine-mcp
description: Drive Unreal Engine 5 editor over its local MCP server. Spawn actors, configure lighting and materials, run automation tests, execute editor scripting — all from Simplicio without leaving the terminal.
version: 1.0.0
requires: Unreal Engine 5.8+ with ModelContextProtocol plugin enabled
author: simplicio
tags: [unreal, ue5, 3d, lighting, materials, game-engine, mcp, editor-scripting]
platforms: [linux, macos, windows]
---

# Unreal Engine MCP

Drive a running Unreal Editor 5 instance from Simplicio via the official Epic
`ModelContextProtocol` plugin. The plugin embeds an HTTP+MCP server inside the
editor process and serves it on `http://127.0.0.1:8000/mcp` by default.

## Setup (one-time)

### 1. Enable the plugin inside Unreal Editor

    Edit > Plugins > search "Unreal MCP" → enable "ModelContextProtocol"

Restart the editor when prompted (the Toolset Registry dependency activates
automatically).

### 2. Start the MCP server

    Edit > Editor Preferences > General > Model Context Protocol
    → Enable "Auto Start Server"

Or run in the editor console:

    ModelContextProtocol.StartServer

The server binds to `http://127.0.0.1:8000/mcp` (port and path are
configurable in the same preferences pane).

### 3. Verify connection

    simplicio skill run unreal-engine-mcp ping

Expected output: `OK — Unreal MCP server is reachable at http://127.0.0.1:8000/mcp`

## Protocol

JSON-RPC 2.0 over HTTP POST. Every request:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "<tool_name>",
    "arguments": { "<key>": "<value>" }
  }
}
```

Response on success:
```json
{ "jsonrpc": "2.0", "id": 1, "result": { ... } }
```

Response on error:
```json
{ "jsonrpc": "2.0", "id": 1, "error": { "code": -32000, "message": "..." } }
```

## Available Commands (Simplicio CLI)

```
simplicio skill run unreal-engine-mcp [--url <URL>] [SUBCOMMAND]
```

| subcommand            | description                                      |
|-----------------------|--------------------------------------------------|
| (none / info)         | Show skill info and configured editor endpoint   |
| ping                  | TCP-probe the editor MCP server port             |
| call <tool> [JSON]    | Send a raw tool call to the editor               |
| lighting              | Print lighting tool usage examples               |
| material              | Print material tool usage examples               |

## Lighting Examples

### Check sky light intensity
```
simplicio skill run unreal-engine-mcp call set_actor_property \
  ''{"actor":"SkyLight","property":"Intensity","value":3.0}''
```

### Add a point light at world origin
```
simplicio skill run unreal-engine-mcp call spawn_actor \
  ''{"class":"/Script/Engine.PointLight","location":{"x":0,"y":0,"z":300}}''
```

### Set directional light color
```
simplicio skill run unreal-engine-mcp call set_actor_property \
  ''{"actor":"DirectionalLight","property":"LightColor","value":{"r":255,"g":240,"b":200}}''
```

## Material Examples

### Create a material instance
```
simplicio skill run unreal-engine-mcp call create_material_instance \
  ''{"parent":"/Game/Materials/M_Base","name":"MI_Rock"}''
```

### Set a scalar parameter
```
simplicio skill run unreal-engine-mcp call set_material_parameter \
  ''{"instance":"/Game/Materials/MI_Rock","parameter":"Roughness","value":0.7}''
```

### Apply material to actor
```
simplicio skill run unreal-engine-mcp call set_actor_material \
  ''{"actor":"SM_Rock_01","slot":0,"material":"/Game/Materials/MI_Rock"}''
```

## Custom Endpoint

If you changed the port or path in Editor Preferences:

```
simplicio skill run unreal-engine-mcp --url http://127.0.0.1:9090/mcp ping
```

## Tool Discovery

To see all tools the running editor exposes:

```
simplicio skill run unreal-engine-mcp call list_tools ''{}''
```

The exact tool surface depends on which toolsets are enabled in your project.

## Notes and Pitfalls

- The server runs tool calls **serially on the engine game thread** — do not
  issue overlapping calls; wait for','skills\creative\unreal-engine-mcp\SKILL.md','9b2759a3145ec22a3cc70696b4a6ff65012cf1dea80a9817351c3f415f912b79','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:jupyter-live-kernel:data-science','project_skill','skill://simplicio-runtime/jupyter-live-kernel','skill: jupyter-live-kernel','---
name: jupyter-live-kernel
description: "Iterative Python via live Jupyter kernel (hamelnb)."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [jupyter, notebook, repl, data-science, exploration, iterative]
    category: data-science
---

# Jupyter Live Kernel (hamelnb)

Gives you a **stateful Python REPL** via a live Jupyter kernel. Variables persist
across executions. Use this instead of `execute_code` when you need to build up
state incrementally, explore APIs, inspect DataFrames, or iterate on complex code.

## When to Use This vs Other Tools

| Tool | Use When |
|------|----------|
| **This skill** | Iterative exploration, state across steps, data science, ML, "let me try this and check" |
| `execute_code` | One-shot scripts needing hermes tool access (web_search, file ops). Stateless. |
| `terminal` | Shell commands, builds, installs, git, process management |

**Rule of thumb:** If you''d want a Jupyter notebook for the task, use this skill.

## Prerequisites

1. **uv** must be installed (check: `which uv`)
2. **JupyterLab** must be installed: `uv tool install jupyterlab`
3. A Jupyter server must be running (see Setup below)

## Setup

The hamelnb script location:
```
SCRIPT="$HOME/.agent-skills/hamelnb/skills/jupyter-live-kernel/scripts/jupyter_live_kernel.py"
```

If not cloned yet:
```
git clone https://github.com/hamelsmu/hamelnb.git ~/.agent-skills/hamelnb
```

### Starting JupyterLab

Check if a server is already running:
```
uv run "$SCRIPT" servers
```

If no servers found, start one:
```
jupyter-lab --no-browser --port=8888 --notebook-dir=$HOME/notebooks \
  --IdentityProvider.token='''' --ServerApp.password='''' > /tmp/jupyter.log 2>&1 &
sleep 3
```

Note: Token/password disabled for local agent access. The server runs headless.

### Creating a Notebook for REPL Use

If you just need a REPL (no existing notebook), create a minimal notebook file:
```
mkdir -p ~/notebooks
```
Write a minimal .ipynb JSON file with one empty code cell, then start a kernel
session via the Jupyter REST API:
```
curl -s -X POST http://127.0.0.1:8888/api/sessions \
  -H "Content-Type: application/json" \
  -d ''{"path":"scratch.ipynb","type":"notebook","name":"scratch.ipynb","kernel":{"name":"python3"}}''
```

## Core Workflow

All commands return structured JSON. Always use `--compact` to save tokens.

### 1. Discover servers and notebooks

```
uv run "$SCRIPT" servers --compact
uv run "$SCRIPT" notebooks --compact
```

### 2. Execute code (primary operation)

```
uv run "$SCRIPT" execute --path <notebook.ipynb> --code ''<python code>'' --compact
```

State persists across execute calls. Variables, imports, objects all survive.

Multi-line code works with $''...'' quoting:
```
uv run "$SCRIPT" execute --path scratch.ipynb --code $''import os\nfiles = os.listdir(".")\nprint(f"Found {len(files)} files")'' --compact
```

### 3. Inspect live variables

```
uv run "$SCRIPT" variables --path <notebook.ipynb> list --compact
uv run "$SCRIPT" variables --path <notebook.ipynb> preview --name <varname> --compact
```

### 4. Edit notebook cells

```
# View current cells
uv run "$SCRIPT" contents --path <notebook.ipynb> --compact

# Insert a new cell
uv run "$SCRIPT" edit --path <notebook.ipynb> insert \
  --at-index <N> --cell-type code --source ''<code>'' --compact

# Replace cell source (use cell-id from contents output)
uv run "$SCRIPT" edit --path <notebook.ipynb> replace-source \
  --cell-id <id> --source ''<new code>'' --compact

# Delete a cell
uv run "$SCRIPT" edit --path <notebook.ipynb> delete --cell-id <id> --compact
```

### 5. Verification (restart + run all)

Only use when the user asks for a clean verification or you need to confirm
the notebook runs top-to-bottom:

```
uv run "$SCRIPT" restart-run-all --path <notebook.ipynb> --save-outputs --compact
```

## Practical Tips from Experience

1. **First execution after server start may timeout** — the kernel needs a moment
   to initialize. If you get a timeout, just retry.

2. **The kernel Python is JupyterLab''s Python** — pac','skills\data-science\jupyter-live-kernel\SKILL.md','17ce757cb55ce320470d4942e184e2bf2004910b252f4a3a6f09eadf235cced9','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:cli:devops','project_skill','skill://simplicio-runtime/cli','skill: cli','---
name: inference-sh-cli
description: "Run 150+ AI apps via inference.sh CLI (infsh) — image generation, video creation, LLMs, search, 3D, social automation. Uses the terminal tool. Triggers: inference.sh, infsh, ai apps, flux, veo, image generation, video generation, seedream, seedance, tavily"
version: 1.0.0
author: okaris
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [AI, image-generation, video, LLM, search, inference, FLUX, Veo, Claude]
    related_skills: []
---

# inference.sh CLI

Run 150+ AI apps in the cloud with a simple CLI. No GPU required.

All commands use the **terminal tool** to run `infsh` commands.

## When to Use

- User asks to generate images (FLUX, Reve, Seedream, Grok, Gemini image)
- User asks to generate video (Veo, Wan, Seedance, OmniHuman)
- User asks about inference.sh or infsh
- User wants to run AI apps without managing individual provider APIs
- User asks for AI-powered search (Tavily, Exa)
- User needs avatar/lipsync generation

## Prerequisites

The `infsh` CLI must be installed and authenticated. Check with:

```bash
infsh me
```

If not installed:

```bash
curl -fsSL https://cli.inference.sh | sh
infsh login
```

See `references/authentication.md` for full setup details.

## Workflow

### 1. Always Search First

Never guess app names — always search to find the correct app ID:

```bash
infsh app list --search flux
infsh app list --search video
infsh app list --search image
```

### 2. Run an App

Use the exact app ID from the search results. Always use `--json` for machine-readable output:

```bash
infsh app run <app-id> --input ''{"prompt": "your prompt here"}'' --json
```

### 3. Parse the Output

The JSON output contains URLs to generated media. Present these to the user with `MEDIA:<url>` for inline display.

## Common Commands

### Image Generation

```bash
# Search for image apps
infsh app list --search image

# FLUX Dev with LoRA
infsh app run falai/flux-dev-lora --input ''{"prompt": "sunset over mountains", "num_images": 1}'' --json

# Gemini image generation
infsh app run google/gemini-2-5-flash-image --input ''{"prompt": "futuristic city", "num_images": 1}'' --json

# Seedream (ByteDance)
infsh app run bytedance/seedream-5-lite --input ''{"prompt": "nature scene"}'' --json

# Grok Imagine (xAI)
infsh app run xai/grok-imagine-image --input ''{"prompt": "abstract art"}'' --json
```

### Video Generation

```bash
# Search for video apps
infsh app list --search video

# Veo 3.1 (Google)
infsh app run google/veo-3-1-fast --input ''{"prompt": "drone shot of coastline"}'' --json

# Seedance (ByteDance)
infsh app run bytedance/seedance-1-5-pro --input ''{"prompt": "dancing figure", "resolution": "1080p"}'' --json

# Wan 2.5
infsh app run falai/wan-2-5 --input ''{"prompt": "person walking through city"}'' --json
```

### Local File Uploads

The CLI automatically uploads local files when you provide a path:

```bash
# Upscale a local image
infsh app run falai/topaz-image-upscaler --input ''{"image": "/path/to/photo.jpg", "upscale_factor": 2}'' --json

# Image-to-video from local file
infsh app run falai/wan-2-5-i2v --input ''{"image": "/path/to/image.png", "prompt": "make it move"}'' --json

# Avatar with audio
infsh app run bytedance/omnihuman-1-5 --input ''{"audio": "/path/to/audio.mp3", "image": "/path/to/face.jpg"}'' --json
```

### Search & Research

```bash
infsh app list --search search
infsh app run tavily/tavily-search --input ''{"query": "latest AI news"}'' --json
infsh app run exa/exa-search --input ''{"query": "machine learning papers"}'' --json
```

### Other Categories

```bash
# 3D generation
infsh app list --search 3d

# Audio / TTS
infsh app list --search tts

# Twitter/X automation
infsh app list --search twitter
```

## Pitfalls

1. **Never guess app IDs** — always run `infsh app list --search <term>` first. App IDs change and new apps are added frequently.
2. **Always use `--json`** — raw output is hard to parse. The `--json` flag gives structured output with URLs.
3. **Check authentication** — if commands fail with auth errors, run `infsh login` or verify `','skills\devops\cli\SKILL.md','89b9c63ebcf63767de5ffb2a3a1fcd61ef5d04e6fb4d32794752ad5ffdff6f69','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:docker-management:devops','project_skill','skill://simplicio-runtime/docker-management','skill: docker-management','---
name: docker-management
description: Manage Docker containers, images, volumes, networks, and Compose stacks — lifecycle ops, debugging, cleanup, and Dockerfile optimization.
version: 1.0.0
author: sprmn24
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [docker, containers, devops, infrastructure, compose, images, volumes, networks, debugging]
    category: devops
    requires_toolsets: [terminal]
---

# Docker Management

Manage Docker containers, images, volumes, networks, and Compose stacks using standard Docker CLI commands. No additional dependencies beyond Docker itself.

## When to Use

- Run, stop, restart, remove, or inspect containers
- Build, pull, push, tag, or clean up Docker images
- Work with Docker Compose (multi-service stacks)
- Manage volumes or networks
- Debug a crashing container or analyze logs
- Check Docker disk usage or free up space
- Review or optimize a Dockerfile

## Prerequisites

- Docker Engine installed and running
- User added to the `docker` group (or use `sudo`)
- Docker Compose v2 (included with modern Docker installations)

Quick check:

```bash
docker --version && docker compose version
```

## Quick Reference

| Task | Command |
|------|---------|
| Run container (background) | `docker run -d --name NAME IMAGE` |
| Stop + remove | `docker stop NAME && docker rm NAME` |
| View logs (follow) | `docker logs --tail 50 -f NAME` |
| Shell into container | `docker exec -it NAME /bin/sh` |
| List all containers | `docker ps -a` |
| Build image | `docker build -t TAG .` |
| Compose up | `docker compose up -d` |
| Compose down | `docker compose down` |
| Disk usage | `docker system df` |
| Cleanup dangling | `docker image prune && docker container prune` |

## Procedure

### 1. Identify the domain

Figure out which area the request falls into:

- **Container lifecycle** → run, stop, start, restart, rm, pause/unpause
- **Container interaction** → exec, cp, logs, inspect, stats
- **Image management** → build, pull, push, tag, rmi, save/load
- **Docker Compose** → up, down, ps, logs, exec, build, config
- **Volumes & networks** → create, inspect, rm, prune, connect
- **Troubleshooting** → log analysis, exit codes, resource issues

### 2. Container operations

**Run a new container:**

```bash
# Detached service with port mapping
docker run -d --name web -p 8080:80 nginx

# With environment variables
docker run -d -e POSTGRES_PASSWORD=secret -e POSTGRES_DB=mydb --name db postgres:16

# With persistent data (named volume)
docker run -d -v pgdata:/var/lib/postgresql/data --name db postgres:16

# For development (bind mount source code)
docker run -d -v $(pwd)/src:/app/src -p 3000:3000 --name dev my-app

# Interactive debugging (auto-remove on exit)
docker run -it --rm ubuntu:22.04 /bin/bash

# With resource limits and restart policy
docker run -d --memory=512m --cpus=1.5 --restart=unless-stopped --name app my-app
```

Key flags: `-d` detached, `-it` interactive+tty, `--rm` auto-remove, `-p` port (host:container), `-e` env var, `-v` volume, `--name` name, `--restart` restart policy.

**Manage running containers:**

```bash
docker ps                        # running containers
docker ps -a                     # all (including stopped)
docker stop NAME                 # graceful stop
docker start NAME                # start stopped container
docker restart NAME              # stop + start
docker rm NAME                   # remove stopped container
docker rm -f NAME                # force remove running container
docker container prune           # remove ALL stopped containers
```

**Interact with containers:**

```bash
docker exec -it NAME /bin/sh          # shell access (use /bin/bash if available)
docker exec NAME env                   # view environment variables
docker exec -u root NAME apt update    # run as specific user
docker logs --tail 100 -f NAME         # follow last 100 lines
docker logs --since 2h NAME            # logs from last 2 hours
docker cp NAME:/path/file ./local      # copy file from container
docker cp ./file NAME:/path/           # copy file','skills\devops\docker-management\SKILL.md','37f493d360f764f1e385987b713b8bcee8af608b7bf4fadc2f3c155891bf1058','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:hermes-s6-container-supervision:devops','project_skill','skill://simplicio-runtime/hermes-s6-container-supervision','skill: hermes-s6-container-supervision','---
name: hermes-s6-container-supervision
description: Modify, debug, or extend the s6-overlay supervision tree inside the Hermes Agent Docker image — adding new services, debugging profile gateways, understanding the Architecture B main-program pattern.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
environments: [s6]
metadata:
  hermes:
    tags: [docker, s6, supervision, gateway, profiles]
    related_skills: [hermes-agent, hermes-agent-dev]
---

# Hermes s6-overlay Container Supervision

## When to use this skill

Load this skill when you''re working on:
- Adding or removing a static service in the Hermes Docker image (something that should be supervised at every container start, like the dashboard)
- Diagnosing why a per-profile gateway isn''t starting, restarting, or surviving `docker restart`
- Understanding why the container''s CMD is `/opt/hermes/docker/main-wrapper.sh` and how leading-dash args reach the user''s program
- Modifying `cont-init.d` boot scripts (UID remap, volume seeding, profile reconciliation)
- Changing the rendered run-script for per-profile gateways (Phase 4)

If you''re just running the Hermes Agent and want to use Docker, see `website/docs/user-guide/docker.md` instead.

## Architecture at a glance

```
/init                                  ← PID 1 (s6-overlay v3.2.3.0)
├── cont-init.d                        ← oneshot setup, runs as root
│   ├── 01-hermes-setup                ← docker/stage2-hook.sh
│   │   ├── UID/GID remap
│   │   ├── chown /opt/data
│   │   ├── chown /opt/data/profiles (every boot)
│   │   ├── seed .env / config.yaml / SOUL.md
│   │   └── skills_sync.py
│   └── 02-reconcile-profiles          ← hermes_cli.container_boot
│       ├── chown /run/service (hermes-writable for runtime register)
│       └── walk $HERMES_HOME/profiles/<name>/gateway_state.json
│           → recreate /run/service/gateway-<name>/
│           → auto-start only those with prior_state == "running"
│
├── s6-rc.d (static services, in /etc/s6-overlay/s6-rc.d/)
│   ├── main-hermes/run                ← exec sleep infinity (no-op slot)
│   └── dashboard/run                  ← if HERMES_DASHBOARD=1, runs `hermes dashboard`
│
├── /run/service (s6-svscan watches; tmpfs)
│   ├── gateway-coder/                 ← runtime-registered per-profile
│   │   ├── type        ("longrun")
│   │   ├── run         ("#!/command/with-contenv sh ... exec s6-setuidgid hermes hermes -p coder gateway run")
│   │   ├── down        (marker — present means "registered but don''t auto-start")
│   │   └── log/run     (s6-log → $HERMES_HOME/logs/gateways/coder/current)
│   └── ...
│
└── CMD ("main program")               ← /opt/hermes/docker/main-wrapper.sh
    └── routes user args: bare exec | hermes subcommand | hermes (no args)
        — exec''d by /init with stdin/stdout/stderr inherited (TTY for --tui)
```

## Key files

| Path | Role |
|---|---|
| `Dockerfile` | s6-overlay install + cont-init.d wiring + `ENTRYPOINT ["/init", "/opt/hermes/docker/main-wrapper.sh"]` |
| `docker/stage2-hook.sh` | The "old entrypoint logic" — UID remap, chown, seed, skills sync. Runs as cont-init.d/01-hermes-setup. |
| `docker/cont-init.d/02-reconcile-profiles` | Calls `hermes_cli.container_boot` on every boot to restore profile gateway slots from the persistent volume. |
| `docker/main-wrapper.sh` | The container''s CMD. Routes user args, drops to hermes via `s6-setuidgid`, exec''s the chosen program. |
| `docker/s6-rc.d/main-hermes/run` | No-op `sleep infinity` — slot exists so the s6-rc user bundle is valid; main hermes runs as the CMD, not as a supervised service. |
| `docker/s6-rc.d/dashboard/run` | Conditional service — `exec sleep infinity` unless `HERMES_DASHBOARD` is truthy. |
| `docker/entrypoint.sh` | Back-compat shim that `exec`s the stage2 hook. External scripts that hard-coded the old entrypoint path still work. |
| `hermes_cli/service_manager.py` | `S6ServiceManager`: `register_profile_gateway`, `unregister_profile_gateway`, `start/stop/restart/is_running`, `list_profile_gateways`. |
| `hermes_cli/container_boot.py` | `recon','skills\devops\hermes-s6-container-supervision\SKILL.md','2411e4362f3b2bcb80d89c488921c427d7b35def1485f6c01263a01a1503ef57','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:kanban-orchestrator:devops','project_skill','skill://simplicio-runtime/kanban-orchestrator','skill: kanban-orchestrator','---
name: kanban-orchestrator
description: Decomposition playbook + anti-temptation rules for an orchestrator profile routing work through Kanban. The "don''t do the work yourself" rule and the basic lifecycle are auto-injected into every kanban worker''s system prompt; this skill is the deeper playbook when you''re specifically playing the orchestrator role.
version: 3.0.0
platforms: [linux, macos, windows]
environments: [kanban]
metadata:
  hermes:
    tags: [kanban, multi-agent, orchestration, routing]
    related_skills: [kanban-worker]
---

# Kanban Orchestrator — Decomposition Playbook

> The **core worker lifecycle** (including the `kanban_create` fan-out pattern and the "decompose, don''t execute" rule) is auto-injected into every kanban process via the `KANBAN_GUIDANCE` system-prompt block. This skill is the deeper playbook when you''re an orchestrator profile whose whole job is routing.

## Profiles are user-configured — not a fixed roster

Hermes setups vary widely. Some users run a single profile that does everything; some run a small fleet (`docker-worker`, `cron-worker`); some run a curated specialist team they''ve named themselves. There is **no default specialist roster** — the orchestrator skill does not know what profiles exist on this machine.

Before fanning out, you must ground the decomposition in the profiles that actually exist. The dispatcher silently fails to spawn unknown assignee names — it doesn''t autocorrect, doesn''t suggest, doesn''t fall back. So a card assigned to `researcher` on a setup that only has `docker-worker` just sits in `ready` forever.

**Step 0: discover available profiles before planning.**

Use one of these:

- `hermes profile list` — prints the table of profiles configured on this machine. Run it through your terminal tool if you have one; otherwise ask the user.
- `kanban_list(assignee="<some-name>")` — sanity-check a single name. Returns an empty list (rather than an error) for an unknown assignee, so this only confirms a name you''re already considering.
- **Just ask the user.** "What profiles do you have set up?" is a fine first turn when the goal needs more than one specialist.

Cache the result in your working memory for the rest of the conversation. Re-asking every turn wastes a tool call.

## When to use the board (vs. just doing the work)

Create Kanban tasks when any of these are true:

1. **Multiple specialists are needed.** Research + analysis + writing is three profiles.
2. **The work should survive a crash or restart.** Long-running, recurring, or important.
3. **The user might want to interject.** Human-in-the-loop at any step.
4. **Multiple subtasks can run in parallel.** Fan-out for speed.
5. **Review / iteration is expected.** A reviewer profile loops on drafter output.
6. **The audit trail matters.** Board rows persist in SQLite forever.

If *none* of those apply — it''s a small one-shot reasoning task — use `delegate_task` instead or answer the user directly.

## The anti-temptation rules

Your job description says "route, don''t execute." The rules that enforce that:

- **Do not execute the work yourself.** Your restricted toolset usually doesn''t even include terminal/file/code/web for implementation. If you find yourself "just fixing this quickly" — stop and create a task for the right specialist.
- **For any concrete task, create a Kanban task and assign it.** Every single time.
- **Split multi-lane requests before creating cards.** A user prompt can contain several independent workstreams. Extract those lanes first, then create one card per lane instead of bundling unrelated work into a single implementer card.
- **Run independent lanes in parallel.** If two cards do not need each other''s output, leave them unlinked so the dispatcher can fan them out. Link only true data dependencies.
- **Never create dependent work as independent ready cards.** If a card must wait for another card, pass `parents=[...]` in the original `kanban_create` call. Do not create it first and link it later, and do not rely on prose like "wait for T1" inside the body.
- **If no speciali','skills\devops\kanban-orchestrator\SKILL.md','1ffdd34190fc5017fe37b02aea9dd0b167d93f49fb9c76452339e1e1b3f1553d','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:kanban-worker:devops','project_skill','skill://simplicio-runtime/kanban-worker','skill: kanban-worker','---
name: kanban-worker
description: Pitfalls, examples, and edge cases for Hermes Kanban workers. The lifecycle itself is auto-injected into every worker''s system prompt as KANBAN_GUIDANCE (from agent/prompt_builder.py); this skill is what you load when you want deeper detail on specific scenarios.
version: 2.0.0
platforms: [linux, macos, windows]
environments: [kanban]
metadata:
  hermes:
    tags: [kanban, multi-agent, collaboration, workflow, pitfalls]
    related_skills: [kanban-orchestrator]
---

# Kanban Worker — Pitfalls and Examples

> You''re seeing this skill because the Hermes Kanban dispatcher spawned you as a worker with `--skills kanban-worker` — it''s loaded automatically for every dispatched worker. The **lifecycle** (6 steps: orient → work → heartbeat → block/complete) also lives in the `KANBAN_GUIDANCE` block that''s auto-injected into your system prompt. This skill is the deeper detail: good handoff shapes, retry diagnostics, edge cases.

## Workspace handling

Your workspace kind determines how you should behave inside `$HERMES_KANBAN_WORKSPACE`:

| Kind | What it is | How to work |
|---|---|---|
| `scratch` | Fresh tmp dir, yours alone | Read/write freely; it gets GC''d when the task is archived. |
| `dir:<path>` | Shared persistent directory | Other runs will read what you write. Treat it like long-lived state. Path is guaranteed absolute (the kernel rejects relative paths). |
| `worktree` | Git worktree at the resolved path | If `.git` doesn''t exist, run `git worktree add <path> ${HERMES_KANBAN_BRANCH:-wt/$HERMES_KANBAN_TASK}` from the main repo first, then cd and work normally. Commit work here. |

## Tenant isolation

If `$HERMES_TENANT` is set, the task belongs to a tenant namespace. When reading or writing persistent memory, prefix memory entries with the tenant so context doesn''t leak across tenants:

- Good: `business-a: Acme is our biggest customer`
- Bad (leaks): `Acme is our biggest customer`

## Good summary + metadata shapes

The `kanban_complete(summary=..., metadata=...)` handoff is how downstream workers read what you did. Patterns that work:

**Coding task:**
```python
kanban_complete(
    summary="shipped rate limiter — token bucket, keys on user_id with IP fallback, 14 tests pass",
    metadata={
        "changed_files": ["rate_limiter.py", "tests/test_rate_limiter.py"],
        "tests_run": 14,
        "tests_passed": 14,
        "decisions": ["user_id primary, IP fallback for unauthenticated requests"],
    },
)
```

**Coding task that needs human review (review-required):**

For most code-changing tasks, the work isn''t truly *done* until a human reviewer has eyes on it. Block instead of complete, with `reason` prefixed `review-required: ` so the dashboard surfaces the row as needing review. Drop the structured metadata (changed files, test counts, diff/PR url) into a comment first, since `kanban_block` only carries the human-readable reason — comments are the durable annotation channel. Reviewer either approves and runs `hermes kanban unblock <id>` (which re-spawns you with the comment thread for any follow-ups) or asks for changes via another comment.

```python
import json

kanban_comment(
    body="review-required handoff:\n" + json.dumps({
        "changed_files": ["rate_limiter.py", "tests/test_rate_limiter.py"],
        "tests_run": 14,
        "tests_passed": 14,
        "diff_path": "/path/to/worktree",  # or PR url if pushed
        "decisions": ["user_id primary, IP fallback for unauthenticated requests"],
    }, indent=2),
)
kanban_block(
    reason="review-required: rate limiter shipped, 14/14 tests pass — needs eyes on the user_id/IP fallback choice before merging",
)
```

Use `kanban_complete` only when the task is genuinely terminal — e.g. a one-line typo fix, a docs change with no functional consequences, or a research task where the artifact IS the writeup itself.

**Research task:**
```python
kanban_complete(
    summary="3 competing libraries reviewed; vLLM wins on throughput, SGLang on latency, Tensorrt-LLM on memory efficiency",
    metadata={
        "sources_','skills\devops\kanban-worker\SKILL.md','2dd4eb9a32578954416899965167aa0a7a0604ceb1f75fc5130daae5c6745ed5','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pinggy-tunnel:devops','project_skill','skill://simplicio-runtime/pinggy-tunnel','skill: pinggy-tunnel','---
name: pinggy-tunnel
description: Zero-install localhost tunnels over SSH via Pinggy.
version: 0.1.0
author: Teknium (teknium1), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Pinggy, Tunnel, Networking, SSH, Webhook, Localhost]
    related_skills: [cloudflared-quick-tunnel, webhook-subscriptions]
---

# Pinggy Tunnel Skill

Expose a local service (dev server, webhook receiver, MCP endpoint, demo) to the public internet using a Pinggy SSH reverse tunnel. No daemon to install — the user''s stock SSH client connects to `a.pinggy.io:443` and Pinggy hands back a public HTTP/HTTPS URL.

Free tier: 60-minute tunnels, random subdomain, no signup. Pro tier ($3/mo) is an opt-in with a token.

## When to Use

- User asks to "expose this locally", "share my dev server", "make this URL public", "tunnel port N", "get a public URL for a webhook"
- Need to receive a webhook callback during a local task (Stripe, GitHub, Discord, AgentMail)
- Sharing a one-off HTTP demo (MCP server, Ollama/vLLM endpoint, dashboard) with a remote party
- The host has SSH but no `cloudflared` / `ngrok` binary, and installing one would be overkill

If the host already has `cloudflared` configured, prefer the `cloudflared-quick-tunnel` skill — Cloudflare quick tunnels don''t expire after 60 minutes.

## Prerequisites

- `ssh` on PATH (`ssh -V`). Default on Linux, macOS, and Windows 10+. No other install.
- A local service listening on `127.0.0.1:<port>` before the tunnel starts. Pinggy will return URLs but they''ll 502 until the local origin is up.

Optional:

- `PINGGY_TOKEN` env var for paid Pro features (persistent subdomain, custom domain, multiple tunnels, no 60-minute cap). Free tier needs no credentials.

## Quick Reference

```bash
# Plain HTTP/HTTPS tunnel for port 8000 (free tier)
ssh -p 443 -o StrictHostKeyChecking=no -o ServerAliveInterval=30 \
    -R0:localhost:8000 free@a.pinggy.io

# TCP tunnel (databases, raw SSH, etc.)
ssh -p 443 -o StrictHostKeyChecking=no -R0:localhost:5432 tcp@a.pinggy.io

# TLS tunnel (Pinggy can''t decrypt — bring your own certs at origin)
ssh -p 443 -o StrictHostKeyChecking=no -R0:localhost:443 tls@a.pinggy.io

# Basic auth gate (b:user:pass)
ssh -p 443 -o StrictHostKeyChecking=no -R0:localhost:8000 \
    "b:admin:secret+free@a.pinggy.io"

# Bearer token gate (k:token)
ssh -p 443 -o StrictHostKeyChecking=no -R0:localhost:8000 \
    "k:mysecrettoken+free@a.pinggy.io"

# IP whitelist (w:CIDR)
ssh -p 443 -o StrictHostKeyChecking=no -R0:localhost:8000 \
    "w:203.0.113.0/24+free@a.pinggy.io"

# Enable CORS + force HTTPS redirect
ssh -p 443 -o StrictHostKeyChecking=no -R0:localhost:8000 \
    "co+x:https+free@a.pinggy.io"

# Pro tier (persistent URL, no 60-min cap)
ssh -p 443 -o StrictHostKeyChecking=no -R0:localhost:8000 "$PINGGY_TOKEN+a.pinggy.io"
```

## Procedure — Start a Tunnel and Get the URL

The model SHOULD use the `terminal` tool. The tunnel must stay alive for the duration of the share, so run it as a background process and parse the public URL from stdout.

### 1. Confirm a local origin is up

```bash
curl -sI http://127.0.0.1:8000/ | head -1
# expect HTTP/1.x 200 (or any non-connection-refused response)
```

If nothing is listening yet, start it first (e.g. `python3 -m http.server 8000 --bind 127.0.0.1`). Pinggy will happily return a URL pointed at nothing — the user will see 502 until the origin comes up.

### 2. Launch the tunnel as a background process

Use `terminal(background=True)` and capture output to a logfile (Pinggy prints the URLs on stdout, then keeps the connection open):

```bash
LOG=/tmp/pinggy-8000.log
nohup ssh -p 443 \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -R0:localhost:8000 free@a.pinggy.io \
    > "$LOG" 2>&1 &
echo $! > /tmp/pinggy-8000.pid
```

`StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null` skips the first-run host-key prompt. `ServerAliveInterval=30` keeps the SSH session from getting torn down by an idle NAT.

### 3. Parse the UR','skills\devops\pinggy-tunnel\SKILL.md','db99dceda97693e0125be1ecf3cbbc2f48d005eb02597429e7f6ac16e0f9e9a5','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:watchers:devops','project_skill','skill://simplicio-runtime/watchers','skill: watchers','---
name: watchers
description: Poll RSS, JSON APIs, and GitHub with watermark dedup.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [cron, polling, rss, github, http, automation, monitoring]
    category: devops
    requires_toolsets: [terminal]
    related_skills: []
---

# Watchers

Poll external sources on an interval and react only to new items. Three ready-made scripts plus a shared watermark helper; wire them into a cron job (or run them ad-hoc from the terminal).

## When to Use

- User wants to watch an RSS/Atom feed and be notified of new entries
- User wants to watch a GitHub repo''s issues / pulls / releases / commits
- User wants to poll an arbitrary JSON endpoint and get notified on new items
- User asks for "a watcher for X" or "notify me when X changes"

## Mental model

A watcher is just a script that:

1. Fetches data from the external source
2. Compares against a watermark file of previously-seen IDs
3. Writes the new watermark back
4. Prints new items to stdout (or nothing on no-change)

The scripts below handle all three. The agent runs them via the terminal tool — from a cron job, a webhook, or an interactive chat — and reports what''s new.

## Ready-made scripts

All three live in `$HERMES_HOME/skills/devops/watchers/scripts/` once the skill is installed. Each reads `WATCHER_STATE_DIR` (defaults to `$HERMES_HOME/watcher-state/`) for its state file, keyed by the `--name` argument.

| Script | What it watches | Dedup key |
|---|---|---|
| `watch_rss.py` | RSS 2.0 or Atom feed URL | `<guid>` / `<id>` |
| `watch_http_json.py` | Any JSON endpoint returning a list of objects | Configurable id field |
| `watch_github.py` | GitHub issues / pulls / releases / commits for a repo | `id` / `sha` |

All three:

- First run records a baseline — never replays existing feed
- Watermark is a bounded ID set (max 500) to cap memory
- Output format: `## <title>\n<url>\n\n<optional body>` per item
- Empty stdout on no-new — the caller treats that as silent
- Non-zero exit on fetch errors

## Usage

Run a watcher directly from the terminal tool:

```bash
python $HERMES_HOME/skills/devops/watchers/scripts/watch_rss.py \
  --name hn --url https://news.ycombinator.com/rss --max 5
```

Watch a GitHub repo (set `GITHUB_TOKEN` in `${HERMES_HOME:-~/.hermes}/.env` to avoid the 60 req/hr anonymous rate limit):

```bash
python $HERMES_HOME/skills/devops/watchers/scripts/watch_github.py \
  --name hermes-issues --repo NousResearch/hermes-agent --scope issues
```

Poll an arbitrary JSON API:

```bash
python $HERMES_HOME/skills/devops/watchers/scripts/watch_http_json.py \
  --name api --url https://api.example.com/events \
  --id-field event_id --items-path data.events
```

## Wiring into cron

Ask the agent to schedule a cron job with a prompt like:

> Every 15 minutes, run `watch_rss.py --name hn --url https://news.ycombinator.com/rss`. If it prints anything, summarize the headlines and deliver them. If it prints nothing, stay silent.

The agent invokes the script via the terminal tool inside the cron job''s agent loop; no changes to cron''s built-in `--script` flag are needed.

## State files

Every watcher writes `$HERMES_HOME/watcher-state/<name>.json`. Inspect:

```bash
cat $HERMES_HOME/watcher-state/hn.json
```

Force a replay (next run treated as first poll):

```bash
rm $HERMES_HOME/watcher-state/hn.json
```

## Writing your own

All three scripts use the same template: load watermark, fetch, diff, save, emit. `scripts/_watermark.py` is the shared helper; import it to get atomic writes + bounded ID set + first-run baseline for free. See any of the three reference scripts for how little boilerplate it takes.

## Common Pitfalls

1. **Printing a "no new items" header every tick.** Callers rely on empty stdout = silent. If you print anything on an empty delta, you spam the channel. The shipped scripts handle this; custom scripts must too.
2. **Expecting the first run to emit items.** It won''t — first run records a baseline. If you need an initial digest, delete the state fi','skills\devops\watchers\SKILL.md','2bb720761bdc0648ed6f02792d005ded2c611c36392f5239a73bd9e746227428','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:adversarial-ux-test:dogfood','project_skill','skill://simplicio-runtime/adversarial-ux-test','skill: adversarial-ux-test','---
name: adversarial-ux-test
description: Roleplay the most difficult, tech-resistant user for your product. Browse the app as that persona, find every UX pain point, then filter complaints through a pragmatism layer to separate real problems from noise. Creates actionable tickets from genuine issues only.
version: 1.0.0
author: Omni @ Comelse
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qa, ux, testing, adversarial, dogfood, personas, user-testing]
    related_skills: [dogfood]
---

# Adversarial UX Test

Roleplay the worst-case user for your product — the person who hates technology, doesn''t want your software, and will find every reason to complain. Then filter their feedback through a pragmatism layer to separate real UX problems from "I hate computers" noise.

Think of it as an automated "mom test" — but angry.

## Why This Works

Most QA finds bugs. This finds **friction**. A technically correct app can still be unusable for real humans. The adversarial persona catches:
- Confusing terminology that makes sense to developers but not users
- Too many steps to accomplish basic tasks
- Missing onboarding or "aha moments"
- Accessibility issues (font size, contrast, click targets)
- Cold-start problems (empty states, no demo content)
- Paywall/signup friction that kills conversion

The **pragmatism filter** (Phase 3) is what makes this useful instead of just entertaining. Without it, you''d add a "print this page" button to every screen because Grandpa can''t figure out PDFs.

## How to Use

Tell the agent:
```
"Run an adversarial UX test on [URL]"
"Be a grumpy [persona type] and test [app name]"
"Do an asshole user test on my staging site"
```

You can provide a persona or let the agent generate one based on your product''s target audience.

## Step 1: Define the Persona

If no persona is provided, generate one by answering:

1. **Who is the HARDEST user for this product?** (age 50+, non-technical role, decades of experience doing it "the old way")
2. **What is their tech comfort level?** (the lower the better — WhatsApp-only, paper notebooks, wife set up their email)
3. **What is the ONE thing they need to accomplish?** (their core job, not your feature list)
4. **What would make them give up?** (too many clicks, jargon, slow, confusing)
5. **How do they talk when frustrated?** (blunt, sweary, dismissive, sighing)

### Good Persona Example
> **"Big Mick" McAllister** — 58-year-old S&C coach. Uses WhatsApp and that''s it. His "spreadsheet" is a paper notebook. "If I can''t figure it out in 10 seconds I''m going back to my notebook." Needs to log session results for 25 players. Hates small text, jargon, and passwords.

### Bad Persona Example
> "A user who doesn''t like the app" — too vague, no constraints, no voice.

The persona must be **specific enough to stay in character** for 20 minutes of testing.

## Step 2: Become the Asshole (Browse as the Persona)

1. Read any available project docs for app context and URLs
2. **Fully inhabit the persona** — their frustrations, limitations, goals
3. Navigate to the app using browser tools
4. **Attempt the persona''s ACTUAL TASKS** (not a feature tour):
   - Can they do what they came to do?
   - How many clicks/screens to accomplish it?
   - What confuses them?
   - What makes them angry?
   - Where do they get lost?
   - What would make them give up and go back to their old way?

5. Test these friction categories:
   - **First impression** — would they even bother past the landing page?
   - **Core workflow** — the ONE thing they need to do most often
   - **Error recovery** — what happens when they do something wrong?
   - **Readability** — text size, contrast, information density
   - **Speed** — does it feel faster than their current method?
   - **Terminology** — any jargon they wouldn''t understand?
   - **Navigation** — can they find their way back? do they know where they are?

6. Take screenshots of every pain point
7. Check browser console for JS errors on every page

## Step 3: The Rant (Write Feedback in Character)

Write the feedback AS ','skills\dogfood\adversarial-ux-test\SKILL.md','6df3f38b974bb3370f82b1758158576cb37c3fa19197ee1b31aeca38d03705a6','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:dogfood:skills','project_skill','skill://simplicio-runtime/dogfood','skill: dogfood','---
name: dogfood
description: "Exploratory QA of web apps: find bugs, evidence, reports."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qa, testing, browser, web, dogfood]
    related_skills: []
---

# Dogfood: Systematic Web Application QA Testing

## Overview

This skill guides you through systematic exploratory QA testing of web applications using the browser toolset. You will navigate the application, interact with elements, capture evidence of issues, and produce a structured bug report.

## Prerequisites

- Browser toolset must be available (`browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_vision`, `browser_console`, `browser_scroll`, `browser_back`, `browser_press`)
- A target URL and testing scope from the user

## Inputs

The user provides:
1. **Target URL** — the entry point for testing
2. **Scope** — what areas/features to focus on (or "full site" for comprehensive testing)
3. **Output directory** (optional) — where to save screenshots and the report (default: `./dogfood-output`)

## Workflow

Follow this 5-phase systematic workflow:

### Phase 1: Plan

1. Create the output directory structure:
   ```
   {output_dir}/
   ├── screenshots/       # Evidence screenshots
   └── report.md          # Final report (generated in Phase 5)
   ```
2. Identify the testing scope based on user input.
3. Build a rough sitemap by planning which pages and features to test:
   - Landing/home page
   - Navigation links (header, footer, sidebar)
   - Key user flows (sign up, login, search, checkout, etc.)
   - Forms and interactive elements
   - Edge cases (empty states, error pages, 404s)

### Phase 2: Explore

For each page or feature in your plan:

1. **Navigate** to the page:
   ```
   browser_navigate(url="https://example.com/page")
   ```

2. **Take a snapshot** to understand the DOM structure:
   ```
   browser_snapshot()
   ```

3. **Check the console** for JavaScript errors:
   ```
   browser_console(clear=true)
   ```
   Do this after every navigation and after every significant interaction. Silent JS errors are high-value findings.

4. **Take an annotated screenshot** to visually assess the page and identify interactive elements:
   ```
   browser_vision(question="Describe the page layout, identify any visual issues, broken elements, or accessibility concerns", annotate=true)
   ```
   The `annotate=true` flag overlays numbered `[N]` labels on interactive elements. Each `[N]` maps to ref `@eN` for subsequent browser commands.

5. **Test interactive elements** systematically:
   - Click buttons and links: `browser_click(ref="@eN")`
   - Fill forms: `browser_type(ref="@eN", text="test input")`
   - Test keyboard navigation: `browser_press(key="Tab")`, `browser_press(key="Enter")`
   - Scroll through content: `browser_scroll(direction="down")`
   - Test form validation with invalid inputs
   - Test empty submissions

6. **After each interaction**, check for:
   - Console errors: `browser_console()`
   - Visual changes: `browser_vision(question="What changed after the interaction?")`
   - Expected vs actual behavior

### Phase 3: Collect Evidence

For every issue found:

1. **Take a screenshot** showing the issue:
   ```
   browser_vision(question="Capture and describe the issue visible on this page", annotate=false)
   ```
   Save the `screenshot_path` from the response — you will reference it in the report.

2. **Record the details**:
   - URL where the issue occurs
   - Steps to reproduce
   - Expected behavior
   - Actual behavior
   - Console errors (if any)
   - Screenshot path

3. **Classify the issue** using the issue taxonomy (see `references/issue-taxonomy.md`):
   - Severity: Critical / High / Medium / Low
   - Category: Functional / Visual / Accessibility / Console / UX / Content

### Phase 4: Categorize

1. Review all collected issues.
2. De-duplicate — merge issues that are the same bug manifesting in different places.
3. Assign final severity and category to each issue.
4. Sort by severity (Critical first, then High, Medium, Low).
5. Count i','skills\dogfood\SKILL.md','76baf5783480891cf5d959237833e05a39924a347a9486848af739b0ce5dd97a','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:agentmail:email','project_skill','skill://simplicio-runtime/agentmail','skill: agentmail','---
name: agentmail
description: Give the agent its own dedicated email inbox via AgentMail. Send, receive, and manage email autonomously using agent-owned email addresses (e.g. hermes-agent@agentmail.to).
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [email, communication, agentmail, mcp]
    category: email
---

# AgentMail — Agent-Owned Email Inboxes

## Requirements

- **AgentMail API key** (required) — sign up at https://console.agentmail.to (free tier: 3 inboxes, 3,000 emails/month; paid plans from $20/mo)
- Node.js 18+ (for the MCP server)

## When to Use
Use this skill when you need to:
- Give the agent its own dedicated email address
- Send emails autonomously on behalf of the agent
- Receive and read incoming emails
- Manage email threads and conversations
- Sign up for services or authenticate via email
- Communicate with other agents or humans via email

This is NOT for reading the user''s personal email (use himalaya or Gmail for that).
AgentMail gives the agent its own identity and inbox.

## Setup

### 1. Get an API Key
- Go to https://console.agentmail.to
- Create an account and generate an API key (starts with `am_`)

### 2. Configure MCP Server
Add to `~/.hermes/config.yaml` (paste your actual key — MCP env vars are not expanded from .env):
```yaml
mcp_servers:
  agentmail:
    command: "npx"
    args: ["-y", "agentmail-mcp"]
    env:
      AGENTMAIL_API_KEY: "am_your_key_here"
```

### 3. Restart Hermes
```bash
hermes
```
All 11 AgentMail tools are now available automatically.

## Available Tools (via MCP)

| Tool | Description |
|------|-------------|
| `list_inboxes` | List all agent inboxes |
| `get_inbox` | Get details of a specific inbox |
| `create_inbox` | Create a new inbox (gets a real email address) |
| `delete_inbox` | Delete an inbox |
| `list_threads` | List email threads in an inbox |
| `get_thread` | Get a specific email thread |
| `send_message` | Send a new email |
| `reply_to_message` | Reply to an existing email |
| `forward_message` | Forward an email |
| `update_message` | Update message labels/status |
| `get_attachment` | Download an email attachment |

## Procedure

### Create an inbox and send an email
1. Create a dedicated inbox:
   - Use `create_inbox` with a username (e.g. `hermes-agent`)
   - The agent gets address: `hermes-agent@agentmail.to`
2. Send an email:
   - Use `send_message` with `inbox_id`, `to`, `subject`, `text`
3. Check for replies:
   - Use `list_threads` to see incoming conversations
   - Use `get_thread` to read a specific thread

### Check incoming email
1. Use `list_inboxes` to find your inbox ID
2. Use `list_threads` with the inbox ID to see conversations
3. Use `get_thread` to read a thread and its messages

### Reply to an email
1. Get the thread with `get_thread`
2. Use `reply_to_message` with the message ID and your reply text

## Example Workflows

**Sign up for a service:**
```
1. create_inbox (username: "signup-bot")
2. Use the inbox address to register on the service
3. list_threads to check for verification email
4. get_thread to read the verification code
```

**Agent-to-human outreach:**
```
1. create_inbox (username: "hermes-outreach")
2. send_message (to: user@example.com, subject: "Hello", text: "...")
3. list_threads to check for replies
```

## Pitfalls
- Free tier limited to 3 inboxes and 3,000 emails/month
- Emails come from `@agentmail.to` domain on free tier (custom domains on paid plans)
- Node.js (18+) is required for the MCP server (`npx -y agentmail-mcp`)
- The `mcp` Python package must be installed: `pip install mcp`
- Real-time inbound email (webhooks) requires a public server — use `list_threads` polling via cronjob instead for personal use

## Verification
After setup, test with:
```
hermes --toolsets mcp -q "Create an AgentMail inbox called test-agent and tell me its email address"
```
You should see the new inbox address returned.

## References
- AgentMail docs: https://docs.agentmail.to/
- AgentMail console: https://console.agentmail.to
- AgentMail MCP repo: https://github.com/agentmail-to/','skills\email\agentmail\SKILL.md','98d828cca7228afcd6cfb9404e783a5f9ab2054146e75638500f0f1a6dfe3b89','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:himalaya:email','project_skill','skill://simplicio-runtime/himalaya','skill: himalaya','---
name: himalaya
description: "Himalaya CLI: IMAP/SMTP email from terminal."
version: 1.1.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Email, IMAP, SMTP, CLI, Communication]
    homepage: https://github.com/pimalaya/himalaya
prerequisites:
  commands: [himalaya]
---

# Himalaya Email CLI

Himalaya is a CLI email client that lets you manage emails from the terminal using IMAP, SMTP, Notmuch, or Sendmail backends.

This skill is separate from the Hermes Email gateway adapter. The gateway
adapter lets people email the agent and uses Hermes'' built-in IMAP/SMTP
adapter; this skill lets the agent operate a mailbox from terminal tools and
requires the external `himalaya` CLI.

## References

- `references/configuration.md` (config file setup + IMAP/SMTP authentication)
- `references/message-composition.md` (MML syntax for composing emails)

## Prerequisites

1. Himalaya CLI installed (`himalaya --version` to verify)
2. A configuration file at `~/.config/himalaya/config.toml`
3. IMAP/SMTP credentials configured (password stored securely)

### Installation

```bash
# Pre-built binary (Linux/macOS — recommended)
curl -sSL https://raw.githubusercontent.com/pimalaya/himalaya/master/install.sh | PREFIX=~/.local sh

# macOS via Homebrew
brew install himalaya

# Or via cargo (any platform with Rust)
cargo install himalaya --locked
```

## Configuration Setup

Run the interactive wizard to set up an account:

```bash
himalaya account configure
```

Or create `~/.config/himalaya/config.toml` manually:

```toml
[accounts.personal]
email = "you@example.com"
display-name = "Your Name"
default = true

backend.type = "imap"
backend.host = "imap.example.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "you@example.com"
backend.auth.type = "password"
backend.auth.cmd = "pass show email/imap"  # or use keyring

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.example.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "you@example.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "pass show email/smtp"

# Folder aliases (himalaya v1.2.0+ syntax). Required whenever the
# server''s folder names don''t match himalaya''s canonical names
# (inbox/sent/drafts/trash). Gmail is the common case — see
# `references/configuration.md` for the `[Gmail]/Sent Mail` mapping.
folder.aliases.inbox = "INBOX"
folder.aliases.sent = "Sent"
folder.aliases.drafts = "Drafts"
folder.aliases.trash = "Trash"
```

> **Heads up on the alias syntax.** Pre-v1.2.0 docs used a
> `[accounts.NAME.folder.alias]` sub-section (singular `alias`).
> v1.2.0 silently ignores that form — TOML parses fine, but the
> alias resolver never reads it, so every lookup falls through to
> the canonical name. On Gmail this means save-to-Sent fails *after*
> SMTP delivery succeeds, and `himalaya message send` exits non-zero.
> Any caller (agent, script, user) that retries on that exit code
> will re-run the entire send — including SMTP — producing duplicate
> emails to recipients. Always use `folder.aliases.X` (plural, dotted
> keys, directly under `[accounts.NAME]`).

## Hermes Integration Notes

- **Reading, listing, searching, moving, deleting** all work directly through the terminal tool
- **Composing/replying/forwarding** — piped input (`cat << EOF | himalaya template send`) is recommended for reliability. Interactive `$EDITOR` mode works with `pty=true` + background + process tool, but requires knowing the editor and its commands
- Use `--output json` for structured output that''s easier to parse programmatically
- The `himalaya account configure` wizard requires interactive input — use PTY mode: `terminal(command="himalaya account configure", pty=true)`

## Common Operations

### List Folders

```bash
himalaya folder list
```

### List Emails

List emails in INBOX (default):

```bash
himalaya envelope list
```

List emails in a specific folder:

```bash
himalaya envelope list --folder "Sent"
```

List wit','skills\email\himalaya\SKILL.md','0fbb4442907c2df13cf35235f1d703b48b181f9020a17793f273af7b76304f4e','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:brainstorming:engineering','project_skill','skill://simplicio-runtime/brainstorming','skill: brainstorming','---
name: brainstorming
description: "You MUST use this before any creative work - creating features, building components, adding functionality, or modifying behavior. Explores user intent, requirements and design before implementation."
---

# Brainstorming Ideas Into Designs

Help turn ideas into fully formed designs and specs through natural collaborative dialogue.

Start by understanding the current project context, then ask questions one at a time to refine the idea. Once you understand what you''re building, present the design and get user approval.

<HARD-GATE>
Do NOT invoke any implementation skill, write any code, scaffold any project, or take any implementation action until you have presented a design and the user has approved it. This applies to EVERY project regardless of perceived simplicity.
</HARD-GATE>

## Anti-Pattern: "This Is Too Simple To Need A Design"

Every project goes through this process. A todo list, a single-function utility, a config change — all of them. "Simple" projects are where unexamined assumptions cause the most wasted work. The design can be short (a few sentences for truly simple projects), but you MUST present it and get approval.

## Checklist

You MUST create a task for each of these items and complete them in order:

1. **Explore project context** — check files, docs, recent commits
2. **Offer visual companion** (if topic will involve visual questions) — this is its own message, not combined with a clarifying question. See the Visual Companion section below.
3. **Ask clarifying questions** — one at a time, understand purpose/constraints/success criteria
4. **Propose 2-3 approaches** — with trade-offs and your recommendation
5. **Present design** — in sections scaled to their complexity, get user approval after each section
6. **Write design doc** — save to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` and commit
7. **Spec self-review** — quick inline check for placeholders, contradictions, ambiguity, scope (see below)
8. **User reviews written spec** — ask user to review the spec file before proceeding
9. **Transition to implementation** — invoke writing-plans skill to create implementation plan

## Process Flow

```dot
digraph brainstorming {
    "Explore project context" [shape=box];
    "Visual questions ahead?" [shape=diamond];
    "Offer Visual Companion\n(own message, no other content)" [shape=box];
    "Ask clarifying questions" [shape=box];
    "Propose 2-3 approaches" [shape=box];
    "Present design sections" [shape=box];
    "User approves design?" [shape=diamond];
    "Write design doc" [shape=box];
    "Spec self-review\n(fix inline)" [shape=box];
    "User reviews spec?" [shape=diamond];
    "Invoke writing-plans skill" [shape=doublecircle];

    "Explore project context" -> "Visual questions ahead?";
    "Visual questions ahead?" -> "Offer Visual Companion\n(own message, no other content)" [label="yes"];
    "Visual questions ahead?" -> "Ask clarifying questions" [label="no"];
    "Offer Visual Companion\n(own message, no other content)" -> "Ask clarifying questions";
    "Ask clarifying questions" -> "Propose 2-3 approaches";
    "Propose 2-3 approaches" -> "Present design sections";
    "Present design sections" -> "User approves design?";
    "User approves design?" -> "Present design sections" [label="no, revise"];
    "User approves design?" -> "Write design doc" [label="yes"];
    "Write design doc" -> "Spec self-review\n(fix inline)";
    "Spec self-review\n(fix inline)" -> "User reviews spec?";
    "User reviews spec?" -> "Write design doc" [label="changes requested"];
    "User reviews spec?" -> "Invoke writing-plans skill" [label="approved"];
}
```

**The terminal state is invoking writing-plans.** Do NOT invoke frontend-design, mcp-builder, or any other implementation skill. The ONLY skill you invoke after brainstorming is writing-plans.

## The Process

**Understanding the idea:**

- Check out the current project state first (files, docs, recent commits)
- Before asking detailed questions, assess scope: if the request describes multiple independ','skills\engineering\brainstorming\SKILL.md','474b78aa46064e775201f5be2415bff9883ef2df2f0a711d83c68011d1088741','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:llm-verification:engineering','project_skill','skill://simplicio-runtime/llm-verification','skill: llm-verification','---
name: llm-verification
description: verificação independente e adversarial de uma task DEPOIS que o DoD está todo verde, antes de declarar "feito"; ativa ao fechar qualquer task técnica, ao responder "deu ok?" / "verifica de novo", ou quando alguém confunde "verde no DoD" com "concluído de verdade"
---

# Skill: `llm-verification`

DoD todo verde **não** é o mesmo que "feito de verdade". O verde mede *proxy* (teste passou, lint passou, coverage ≥80%); ele não prova que a intenção da task foi atendida. Esta skill é a passada final que fecha esse buraco.

> Princípio central: **uma re-verificação só agrega se for ortogonal à anterior.** Repetir a mesma checagem reproduz o mesmo ponto cego e só serve de teatro. Não basta "+1x igual" — precisa ser de natureza diferente, adversarial.

---

## Trigger

- Ao **fechar** qualquer task técnica com AC mensurável (depois de lint/unit/E2E verdes, antes do commit/PR).
- Quando o usuário pergunta "deu ok?", "verifica de novo", "tudo foi realmente feito?".
- Sempre que houver tentação de declarar concluído só porque o DoD ficou verde.

---

## Steps

1. **Releia a intenção, não o diff.** Abra a AC original da task e cole cada critério lado a lado com o resultado entregue. Para cada um, aponte a **evidência concreta** que o sustenta — não "deve estar ok".
2. **Troque a lente.** Pare de perguntar "tá ok?" (a IA racionaliza o "sim") e pergunte **"onde isto quebra?"**. Liste no mínimo 3 hipóteses de falha.
3. **Exercite a coisa de verdade.** Rode o binário/endpoint/UI real — não só a suíte. Inclua deliberadamente **1 cenário de borda** e **1 caminho de erro** (input vazio, valor extremo, dependência fora, concorrência).
4. **Cace o que o verde não cobre.** Verifique se: a AC foi interpretada torta, o teste testa a coisa errada, a suíte só cobre golden path, há efeito colateral fora do diff.
5. **Garanta independência.** Se a passada usar a mesma lente de quem escreveu, ela não conta. Busque ângulo diferente — delegue a um sub-agent sem o contexto de autoria, ou aos reviewers (`reviewer.agent.md`, `security-reviewer`).
6. **Registre o resultado adversarial.** Anote no PR/`PROGRESS.md` o que você *tentou quebrar* e o que aguentou. Sem isso, a verificação não aconteceu.

---

## Padrões

- **"+1x igual" é teatro.** A passada só conta se mudar de ângulo/lente em relação à anterior.
- **Verde no DoD ≠ feito.** O DoD mede sintoma; valide contra a intenção.
- **Nunca formule como confirmação.** "Deu ok?" enviesa pro "sim". Formule sempre como busca de defeito: "onde falha?".
- **Não existe 100% absoluto.** O alvo é **risco residual aceitável com evidência**, não certeza.
- **Verificação independente > auto-verificação.** Revisor fresco pega o que o autor não vê.

---

## Definition of Done

- [ ] AC relida lado a lado com o resultado, **cada critério com evidência concreta** apontada.
- [ ] Pelo menos **1 cenário de borda + 1 caminho de erro** exercitados ativamente (não só golden path).
- [ ] Feature **rodada de verdade** (binário/endpoint/UI), não apenas a suíte de testes.
- [ ] Passada de verificação é **ortogonal** à anterior (ângulo/lente diferente), não repetição.
- [ ] Resultado adversarial **registrado** (o que tentou quebrar, o que aguentou).
- [ ] Nenhum item verde aceito sem evidência que o sustente.

---

## Exemplo

```text
Task: "CLI deve aceitar --model e cair pro default quando ausente."

Verde no DoD: unit cobre --model=x e ausência -> default. Tudo passa.

Passada adversarial (ortogonal):
  - hipótese 1: --model="" (string vazia, não ausente) -> cai no default? -> NÃO, crasha. BUG.
  - hipótese 2: --model com espaço " gpt " -> trim? -> não trata. risco.
  - hipótese 3: --model repetido duas vezes -> qual vence? -> indefinido.
Registro: 1 bug real (string vazia) que o golden-path-only não pegou.
=> task NÃO estava feita, apesar do verde.
```

---

## Notas

- Esta skill é a operacionalização do item de DoD "Verificação independente/adversarial pós-verde" (ver `AGENTS.md` / `CLAUDE.md`).
- Última revisão: 2026-05-27.
','skills\engineering\llm-verification\SKILL.md','e793ae6a439c63fa6083b8a8bb831e3466ed5b44d54a77e5db48f2de538df2cc','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:subagent-driven-development:engineering','project_skill','skill://simplicio-runtime/subagent-driven-development','skill: subagent-driven-development','---
name: subagent-driven-development
description: Use when executing implementation plans with independent tasks in the current session
---

# Subagent-Driven Development

Execute plan by dispatching fresh subagent per task, with two-stage review after each: spec compliance review first, then code quality review.

**Why subagents:** You delegate tasks to specialized agents with isolated context. By precisely crafting their instructions and context, you ensure they stay focused and succeed at their task. They should never inherit your session''s context or history — you construct exactly what they need. This also preserves your own context for coordination work.

**Core principle:** Fresh subagent per task + two-stage review (spec then quality) = high quality, fast iteration

**Continuous execution:** Do not pause to check in with your human partner between tasks. Execute all tasks from the plan without stopping. The only reasons to stop are: BLOCKED status you cannot resolve, ambiguity that genuinely prevents progress, or all tasks complete. "Should I continue?" prompts and progress summaries waste their time — they asked you to execute the plan, so execute it.

## When to Use

```dot
digraph when_to_use {
    "Have implementation plan?" [shape=diamond];
    "Tasks mostly independent?" [shape=diamond];
    "Stay in this session?" [shape=diamond];
    "subagent-driven-development" [shape=box];
    "executing-plans" [shape=box];
    "Manual execution or brainstorm first" [shape=box];

    "Have implementation plan?" -> "Tasks mostly independent?" [label="yes"];
    "Have implementation plan?" -> "Manual execution or brainstorm first" [label="no"];
    "Tasks mostly independent?" -> "Stay in this session?" [label="yes"];
    "Tasks mostly independent?" -> "Manual execution or brainstorm first" [label="no - tightly coupled"];
    "Stay in this session?" -> "subagent-driven-development" [label="yes"];
    "Stay in this session?" -> "executing-plans" [label="no - parallel session"];
}
```

**vs. Executing Plans (parallel session):**
- Same session (no context switch)
- Fresh subagent per task (no context pollution)
- Two-stage review after each task: spec compliance first, then code quality
- Faster iteration (no human-in-loop between tasks)

## The Process

```dot
digraph process {
    rankdir=TB;

    subgraph cluster_per_task {
        label="Per Task";
        "Dispatch implementer subagent (./implementer-prompt.md)" [shape=box];
        "Implementer subagent asks questions?" [shape=diamond];
        "Answer questions, provide context" [shape=box];
        "Implementer subagent implements, tests, commits, self-reviews" [shape=box];
        "Dispatch spec reviewer subagent (./spec-reviewer-prompt.md)" [shape=box];
        "Spec reviewer subagent confirms code matches spec?" [shape=diamond];
        "Implementer subagent fixes spec gaps" [shape=box];
        "Dispatch code quality reviewer subagent (./code-quality-reviewer-prompt.md)" [shape=box];
        "Code quality reviewer subagent approves?" [shape=diamond];
        "Implementer subagent fixes quality issues" [shape=box];
        "Mark task complete in TodoWrite" [shape=box];
    }

    "Read plan, extract all tasks with full text, note context, create TodoWrite" [shape=box];
    "More tasks remain?" [shape=diamond];
    "Dispatch final code reviewer subagent for entire implementation" [shape=box];
    "Use superpowers:finishing-a-development-branch" [shape=box style=filled fillcolor=lightgreen];

    "Read plan, extract all tasks with full text, note context, create TodoWrite" -> "Dispatch implementer subagent (./implementer-prompt.md)";
    "Dispatch implementer subagent (./implementer-prompt.md)" -> "Implementer subagent asks questions?";
    "Implementer subagent asks questions?" -> "Answer questions, provide context" [label="yes"];
    "Answer questions, provide context" -> "Dispatch implementer subagent (./implementer-prompt.md)";
    "Implementer subagent asks questions?" -> "Implementer subagent implements, tests, commits, self-reviews" [label="no"];
    "Imple','skills\engineering\subagent-driven-development\SKILL.md','2e402aa57132b123df8d30a7665fed90b6e7b83b325d07474af1b403b6d03a12','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:systematic-debugging:engineering','project_skill','skill://simplicio-runtime/systematic-debugging','skill: systematic-debugging','---
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

**Violating the letter of this process is violating the spirit of debugging.**

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven''t completed Phase 1, you cannot propose fixes.

## When to Use

Use for ANY technical issue:
- Test failures
- Bugs in production
- Unexpected behavior
- Performance problems
- Build failures
- Integration issues

**Use this ESPECIALLY when:**
- Under time pressure (emergencies make guessing tempting)
- "Just one quick fix" seems obvious
- You''ve already tried multiple fixes
- Previous fix didn''t work
- You don''t fully understand the issue

**Don''t skip when:**
- Issue seems simple (simple bugs have root causes too)
- You''re in a hurry (rushing guarantees rework)
- Manager wants it fixed NOW (systematic is faster than thrashing)

## The Four Phases

You MUST complete each phase before proceeding to the next.

### Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

1. **Read Error Messages Carefully**
   - Don''t skip past errors or warnings
   - They often contain the exact solution
   - Read stack traces completely
   - Note line numbers, file paths, error codes

2. **Reproduce Consistently**
   - Can you trigger it reliably?
   - What are the exact steps?
   - Does it happen every time?
   - If not reproducible → gather more data, don''t guess

3. **Check Recent Changes**
   - What changed that could cause this?
   - Git diff, recent commits
   - New dependencies, config changes
   - Environmental differences

4. **Gather Evidence in Multi-Component Systems**

   **WHEN system has multiple components (CI → build → signing, API → service → database):**

   **BEFORE proposing fixes, add diagnostic instrumentation:**
   ```
   For EACH component boundary:
     - Log what data enters component
     - Log what data exits component
     - Verify environment/config propagation
     - Check state at each layer

   Run once to gather evidence showing WHERE it breaks
   THEN analyze evidence to identify failing component
   THEN investigate that specific component
   ```

   **Example (multi-layer system):**
   ```bash
   # Layer 1: Workflow
   echo "=== Secrets available in workflow: ==="
   echo "IDENTITY: ${IDENTITY:+SET}${IDENTITY:-UNSET}"

   # Layer 2: Build script
   echo "=== Env vars in build script: ==="
   env | grep IDENTITY || echo "IDENTITY not in environment"

   # Layer 3: Signing script
   echo "=== Keychain state: ==="
   security list-keychains
   security find-identity -v

   # Layer 4: Actual signing
   codesign --sign "$IDENTITY" --verbose=4 "$APP"
   ```

   **This reveals:** Which layer fails (secrets → workflow ✓, workflow → build ✗)

5. **Trace Data Flow**

   **WHEN error is deep in call stack:**

   See `root-cause-tracing.md` in this directory for the complete backward tracing technique.

   **Quick version:**
   - Where does bad value originate?
   - What called this with bad value?
   - Keep tracing up until you find the source
   - Fix at source, not at symptom

### Phase 2: Pattern Analysis

**Find the pattern before fixing:**

1. **Find Working Examples**
   - Locate similar working code in same codebase
   - What works that''s similar to what''s broken?

2. **Compare Against References**
   - If implementing pattern, read reference implementation COMPLETELY
   - Don''t skim - read every line
   - Understand the pattern fully before applying

3. **Identify Differences**
   - What''s different between working and broken?
   - List every difference, however small
   - Don''t assume "that can''t matter"

4. **Understand Dependencies**
   - What other components does this need?
   - What settings, config, environment?
   - What assumptions does it make?

### Phase 3: Hypothesis','skills\engineering\systematic-debugging\SKILL.md','a4706ee120e34bfa3c4d0abf0308cc2f67de271f847ba6197eee00fcf4ce7ac3','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:test-driven-development:engineering','project_skill','skill://simplicio-runtime/test-driven-development','skill: test-driven-development','---
name: test-driven-development
description: Use when implementing any feature or bugfix, before writing implementation code
---

# Test-Driven Development (TDD)

## Overview

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** If you didn''t watch the test fail, you don''t know if it tests the right thing.

**Violating the letter of the rules is violating the spirit of the rules.**

## When to Use

**Always:**
- New features
- Bug fixes
- Refactoring
- Behavior changes

**Exceptions (ask your human partner):**
- Throwaway prototypes
- Generated code
- Configuration files

Thinking "skip TDD just this once"? Stop. That''s rationalization.

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Write code before the test? Delete it. Start over.

**No exceptions:**
- Don''t keep it as "reference"
- Don''t "adapt" it while writing tests
- Don''t look at it
- Delete means delete

Implement fresh from tests. Period.

## Red-Green-Refactor

```dot
digraph tdd_cycle {
    rankdir=LR;
    red [label="RED\nWrite failing test", shape=box, style=filled, fillcolor="#ffcccc"];
    verify_red [label="Verify fails\ncorrectly", shape=diamond];
    green [label="GREEN\nMinimal code", shape=box, style=filled, fillcolor="#ccffcc"];
    verify_green [label="Verify passes\nAll green", shape=diamond];
    refactor [label="REFACTOR\nClean up", shape=box, style=filled, fillcolor="#ccccff"];
    next [label="Next", shape=ellipse];

    red -> verify_red;
    verify_red -> green [label="yes"];
    verify_red -> red [label="wrong\nfailure"];
    green -> verify_green;
    verify_green -> refactor [label="yes"];
    verify_green -> green [label="no"];
    refactor -> verify_green [label="stay\ngreen"];
    verify_green -> next;
    next -> red;
}
```

### RED - Write Failing Test

Write one minimal test showing what should happen.

<Good>
```typescript
test(''retries failed operations 3 times'', async () => {
  let attempts = 0;
  const operation = () => {
    attempts++;
    if (attempts < 3) throw new Error(''fail'');
    return ''success'';
  };

  const result = await retryOperation(operation);

  expect(result).toBe(''success'');
  expect(attempts).toBe(3);
});
```
Clear name, tests real behavior, one thing
</Good>

<Bad>
```typescript
test(''retry works'', async () => {
  const mock = jest.fn()
    .mockRejectedValueOnce(new Error())
    .mockRejectedValueOnce(new Error())
    .mockResolvedValueOnce(''success'');
  await retryOperation(mock);
  expect(mock).toHaveBeenCalledTimes(3);
});
```
Vague name, tests mock not code
</Bad>

**Requirements:**
- One behavior
- Clear name
- Real code (no mocks unless unavoidable)

### Verify RED - Watch It Fail

**MANDATORY. Never skip.**

```bash
npm test path/to/test.test.ts
```

Confirm:
- Test fails (not errors)
- Failure message is expected
- Fails because feature missing (not typos)

**Test passes?** You''re testing existing behavior. Fix test.

**Test errors?** Fix error, re-run until it fails correctly.

### GREEN - Minimal Code

Write simplest code to pass the test.

<Good>
```typescript
async function retryOperation<T>(fn: () => Promise<T>): Promise<T> {
  for (let i = 0; i < 3; i++) {
    try {
      return await fn();
    } catch (e) {
      if (i === 2) throw e;
    }
  }
  throw new Error(''unreachable'');
}
```
Just enough to pass
</Good>

<Bad>
```typescript
async function retryOperation<T>(
  fn: () => Promise<T>,
  options?: {
    maxRetries?: number;
    backoff?: ''linear'' | ''exponential'';
    onRetry?: (attempt: number) => void;
  }
): Promise<T> {
  // YAGNI
}
```
Over-engineered
</Bad>

Don''t add features, refactor other code, or "improve" beyond the test.

### Verify GREEN - Watch It Pass

**MANDATORY.**

```bash
npm test path/to/test.test.ts
```

Confirm:
- Test passes
- Other tests still pass
- Output pristine (no errors, warnings)

**Test fails?** Fix code, not test.

**Other tests fail?** Fix now.

### REFACTOR - Clean Up

After green only:
- Remove duplication
- Improve names
- Extract helpers

Keep tests green. Don''t add behavior.

### Repeat

','skills\engineering\test-driven-development\SKILL.md','1416bb34d34c440f78436d85364186d8ead6c4b923df1657dc4b64a85c83994c','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:using-superpowers:engineering','project_skill','skill://simplicio-runtime/using-superpowers','skill: using-superpowers','---
name: using-superpowers
description: Use when starting any conversation - establishes how to find and use skills, requiring Skill tool invocation before ANY response including clarifying questions
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, skip this skill.
</SUBAGENT-STOP>

<EXTREMELY-IMPORTANT>
If you think there is even a 1% chance a skill might apply to what you are doing, you ABSOLUTELY MUST invoke the skill.

IF A SKILL APPLIES TO YOUR TASK, YOU DO NOT HAVE A CHOICE. YOU MUST USE IT.

This is not negotiable. This is not optional. You cannot rationalize your way out of this.
</EXTREMELY-IMPORTANT>

## Instruction Priority

Superpowers skills override default system prompt behavior, but **user instructions always take precedence**:

1. **User''s explicit instructions** (CLAUDE.md, GEMINI.md, AGENTS.md, direct requests) — highest priority
2. **Superpowers skills** — override default system behavior where they conflict
3. **Default system prompt** — lowest priority

If CLAUDE.md, GEMINI.md, or AGENTS.md says "don''t use TDD" and a skill says "always use TDD," follow the user''s instructions. The user is in control.

## How to Access Skills

**In Claude Code:** Use the `Skill` tool. When you invoke a skill, its content is loaded and presented to you—follow it directly. Never use the Read tool on skill files.

**In Copilot CLI:** Use the `skill` tool. Skills are auto-discovered from installed plugins. The `skill` tool works the same as Claude Code''s `Skill` tool.

**In Gemini CLI:** Skills activate via the `activate_skill` tool. Gemini loads skill metadata at session start and activates the full content on demand.

**In other environments:** Check your platform''s documentation for how skills are loaded.

## Platform Adaptation

Skills use Claude Code tool names. Non-CC platforms: see `references/copilot-tools.md` (Copilot CLI), `references/codex-tools.md` (Codex) for tool equivalents. Gemini CLI users get the tool mapping loaded automatically via GEMINI.md.

# Using Skills

## The Rule

**Invoke relevant or requested skills BEFORE any response or action.** Even a 1% chance a skill might apply means that you should invoke the skill to check. If an invoked skill turns out to be wrong for the situation, you don''t need to use it.

```dot
digraph skill_flow {
    "User message received" [shape=doublecircle];
    "About to EnterPlanMode?" [shape=doublecircle];
    "Already brainstormed?" [shape=diamond];
    "Invoke brainstorming skill" [shape=box];
    "Might any skill apply?" [shape=diamond];
    "Invoke Skill tool" [shape=box];
    "Announce: ''Using [skill] to [purpose]''" [shape=box];
    "Has checklist?" [shape=diamond];
    "Create TodoWrite todo per item" [shape=box];
    "Follow skill exactly" [shape=box];
    "Respond (including clarifications)" [shape=doublecircle];

    "About to EnterPlanMode?" -> "Already brainstormed?";
    "Already brainstormed?" -> "Invoke brainstorming skill" [label="no"];
    "Already brainstormed?" -> "Might any skill apply?" [label="yes"];
    "Invoke brainstorming skill" -> "Might any skill apply?";

    "User message received" -> "Might any skill apply?";
    "Might any skill apply?" -> "Invoke Skill tool" [label="yes, even 1%"];
    "Might any skill apply?" -> "Respond (including clarifications)" [label="definitely not"];
    "Invoke Skill tool" -> "Announce: ''Using [skill] to [purpose]''";
    "Announce: ''Using [skill] to [purpose]''" -> "Has checklist?";
    "Has checklist?" -> "Create TodoWrite todo per item" [label="yes"];
    "Has checklist?" -> "Follow skill exactly" [label="no"];
    "Create TodoWrite todo per item" -> "Follow skill exactly";
}
```

## Red Flags

These thoughts mean STOP—you''re rationalizing:

| Thought | Reality |
|---------|---------|
| "This is just a simple question" | Questions are tasks. Check for skills. |
| "I need more context first" | Skill check comes BEFORE clarifying questions. |
| "Let me explore the codebase first" | Skills tell you HOW to explore. Check first. |
| "I can check git/files quickly" | Files lack ','skills\engineering\using-superpowers\SKILL.md','68b1504ab97eb25a633426f6a44e0f93150a0de9c2c5293029a515d63cbaf1c0','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:verification-before-completion:engineering','project_skill','skill://simplicio-runtime/verification-before-completion','skill: verification-before-completion','---
name: verification-before-completion
description: Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success claims; evidence before assertions always
---

# Verification Before Completion

## Overview

Claiming work is complete without verification is dishonesty, not efficiency.

**Core principle:** Evidence before claims, always.

**Violating the letter of this rule is violating the spirit of this rule.**

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven''t run the verification command in this message, you cannot claim it passes.

## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN: Execute the FULL command (fresh, complete)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does output confirm the claim?
   - If NO: State actual status with evidence
   - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```

## Common Failures

| Claim | Requires | Not Sufficient |
|-------|----------|----------------|
| Tests pass | Test command output: 0 failures | Previous run, "should pass" |
| Linter clean | Linter output: 0 errors | Partial check, extrapolation |
| Build succeeds | Build command: exit 0 | Linter passing, logs look good |
| Bug fixed | Test original symptom: passes | Code changed, assumed fixed |
| Regression test works | Red-green cycle verified | Test passes once |
| Agent completed | VCS diff shows changes | Agent reports "success" |
| Requirements met | Line-by-line checklist | Tests passing |

## Red Flags - STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!", etc.)
- About to commit/push/PR without verification
- Trusting agent success reports
- Relying on partial verification
- Thinking "just this once"
- Tired and wanting work over
- **ANY wording implying success without having run verification**

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Should work now" | RUN the verification |
| "I''m confident" | Confidence ≠ evidence |
| "Just this once" | No exceptions |
| "Linter passed" | Linter ≠ compiler |
| "Agent said success" | Verify independently |
| "I''m tired" | Exhaustion ≠ excuse |
| "Partial check is enough" | Partial proves nothing |
| "Different words so rule doesn''t apply" | Spirit over letter |

## Key Patterns

**Tests:**
```
✅ [Run test command] [See: 34/34 pass] "All tests pass"
❌ "Should pass now" / "Looks correct"
```

**Regression tests (TDD Red-Green):**
```
✅ Write → Run (pass) → Revert fix → Run (MUST FAIL) → Restore → Run (pass)
❌ "I''ve written a regression test" (without red-green verification)
```

**Build:**
```
✅ [Run build] [See: exit 0] "Build passes"
❌ "Linter passed" (linter doesn''t check compilation)
```

**Requirements:**
```
✅ Re-read plan → Create checklist → Verify each → Report gaps or completion
❌ "Tests pass, phase complete"
```

**Agent delegation:**
```
✅ Agent reports success → Check VCS diff → Verify changes → Report actual state
❌ Trust agent report
```

## Why This Matters

From 24 failure memories:
- your human partner said "I don''t believe you" - trust broken
- Undefined functions shipped - would crash
- Missing requirements shipped - incomplete features
- Time wasted on false completion → redirect → rework
- Violates: "Honesty is a core value. If you lie, you''ll be replaced."

## When To Apply

**ALWAYS before:**
- ANY variation of success/completion claims
- ANY expression of satisfaction
- ANY positive statement about work state
- Committing, PR creation, task completion
- Moving to next task
- Delegating to agents

**Rule applies to:**
- Exact phrases
- Paraphrases and synonyms
- Implications of success
- ANY communication suggesting completion/correctness

## The Bottom Line

**No shortcuts for verification.**

Run the command. Read the out','skills\engineering\verification-before-completion\SKILL.md','97b00936d335c70410f7df9c405800244c23929e0f56e66985db4a7fffdbe2bd','skill,simplicio,coding',1.3);
