# 🎬 simplicio-loop — vídeo-tutorial multilíngue (hyperframes / HeyGen)

Roteiro dinâmico, com efeitos e som, em **4 idiomas na ordem EN → ZH → ES → PT**, renderizado
com **[hyperframes](https://github.com/heygen-com/hyperframes)** (HeyGen) — HTML→MP4 determinístico,
o mesmo produtor que o `video_evidence` do projeto usa.

## Estrutura

```
video/
├── storyboard.master.json     # MESTRE (language-agnostic): 12 cenas · efeitos · som · timing
├── lang/
│   ├── en.json  zh-CN.json  es.json  pt-BR.json   # caption + narração por cena, por idioma
│   └── en.srt   zh-CN.srt   es.srt   pt-BR.srt    # legendas (geradas de *.json)
├── build_composition.py       # *.json → video/hyperframes/<lang>/index.html (schema hyperframes 0.7.x)
├── build_srt.py               # *.json → *.srt (timing do storyboard)
├── render.sh                  # driver: lint + render por idioma + modo reel
├── hyperframes/<lang>/        # composição HTML pronta p/ render (gerada)
└── out/                       # MP4s renderizados
```

A fonte de TODOS os dados técnicos exibidos no vídeo é o
[`simplicio-loop.project.json`](../simplicio-loop.project.json) — um artefato de dados
**curado manualmente** (não gerado por nenhum script deste repo; ver `$schema_note` no próprio
arquivo), por isso permanece versionado como fonte.

## `video/out/` é efêmero (#116)

`video/out/` (MP4s renderizados) e qualquer `**/_audio_tmp/` (WAV/AIFF intermediários do mux de
áudio) são **saída regenerável, não fonte** — estão no `.gitignore` e não devem ser commitados.
Recrie-os localmente com `bash video/render.sh` (ou `bash video/render.sh <lang>` /
`bash video/render.sh reel`); nada no restante do repo (`scripts/check.py`, os workers de
evidência) lê esses arquivos do git, então removê-los do tracking não quebra validação nenhuma.
Um `git filter-repo` para apagar esses blobs do histórico antigo é uma decisão separada, que
requer aprovação explícita do mantenedor — não foi feita automaticamente aqui.

## As 12 cenas

| # | cena | mostra |
|---|---|---|
| 1 | hook | "Não é um chatbot. É um trabalhador." + loop ♾️ |
| 2 | problem | filas (Issues/CI/Jira) + custo de tokens explodindo |
| 3 | preflight | auth ✓ · runtime/tools ✓ · STOP path ✓ |
| 4 | discover_dag | 50 issues · dedup · DAG · fleet=14 |
| 5 | cycle | read→orient→plan→edit→RUN→verify→PR (WORKS not just compiles) |
| 6 | quality_safety | review adversarial (3 rubricas) · action_gate FAIL-CLOSED |
| 7 | token_economy | leitura só de assinaturas · dashboard :9090 · economia só conta quando medida |
| 8 | evidence_loop | `<promise>` só com prova · stall detector · nunca falso "done" |
| 9 | video_evidence | web_verify → hyperframes → MP4 determinístico no PR |
| 10 | runtimes | um protocolo para todos os runtimes — só a velocidade difere |
| 11 | always_on | merge · close · idle · acorda — 24/7 |
| 12 | cta | pip install · MIT · GitHub ⭐ · Discord |

Cada idioma dura ~123s. Efeitos por cena (transições, partículas, glow, camera, SFX) estão em
`storyboard.master.json` → `scenes[].effects` / `.sound` e no kit global `global_effects_kit`.

## Render (1 comando)

```bash
bash video/render.sh            # gera composições + renderiza os 4 idiomas → video/out/*.mp4
bash video/render.sh pt-BR      # um idioma só
bash video/render.sh reel       # 1 MP4 concatenando EN→ZH→ES→PT
```

Por baixo (equivalente manual, por idioma):

```bash
python3 video/build_composition.py            # *.json → video/hyperframes/<lang>/index.html
cd video/hyperframes/pt-BR
npx hyperframes lint                           # valida a composição (0 errors esperado)
npx hyperframes render . -o ../../out/simplicio-loop_pt-BR.mp4 -f 30 -q high
```

Requisitos (o produtor BLOCK, nunca fake-pass, se faltar): **Node.js 22+**, **FFmpeg**, hyperframes
(via `npx`, sem instalação global). Verificado neste repo: Node v22.x · FFmpeg 8.x · hyperframes 0.7.6.

## Som + narração (HeyGen TTS)

A composição hyperframes é **visual** (HTML→MP4 determinístico). O **áudio** entra como faixa
separada e é mixado no fim — nunca vai pro contexto do LLM (token economy). Fluxo:

1. **Narração (voz):** gere TTS por idioma a partir de `lang/<lang>.json[].narration`. Hint de voz
   em cada arquivo (`tts_voice_hint`). HeyGen TTS/avatar ou um MCP de áudio servem.
2. **Música + SFX:** `storyboard.master.json` → `video.audio` (music bed, mix -16 LUFS) e
   `global_effects_kit.sfx_library` + `scenes[].sound`.
3. **Mux final:** `ffmpeg -i simplicio-loop_<lang>.mp4 -i narration_<lang>.wav -i music.wav \
   -filter_complex amix=inputs=2 -c:v copy -shortest simplicio-loop_<lang>_av.mp4`.
4. **Legendas:** queime ou anexe `lang/<lang>.srt` (`-vf subtitles=...` ou track soft).

## Dois modos de entrega

- **separate** — 4 MP4s (um por idioma), ideal p/ canais segmentados.
- **reel** — 1 MP4 com os 4 idiomas em sequência (EN→ZH→ES→PT, ~8min12s) + card de transição
  entre versões (`storyboard.master.json` → `language_card_between_versions`). `bash video/render.sh reel`.

## Editar / estender

- **Texto/idioma:** edite `lang/<lang>.json` → rode `build_composition.py` + `build_srt.py`.
- **Visual/efeitos/timing:** edite `storyboard.master.json` (mude `duration_s`/`effects`/`sound`).
- **Novo idioma:** adicione `lang/<xx>.json` (mesma estrutura de cenas) e inclua `xx` em
  `LANGS` de `build_composition.py`, `build_srt.py` e `render.sh`.
- O lint pode avisar `timeline_track_too_dense` (12 elementos numa track) — é só uma sugestão de
  legibilidade; não bloqueia o render.
