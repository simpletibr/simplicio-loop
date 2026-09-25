// Cue sheet — SFX cues a serem aplicados em editor externo (CapCut/Premiere) ou
// localmente via `<Audio>` apontando para arquivos em assets/sfx/ (não bundlados
// no repo para manter o tarball leve). Frames calculados a partir do TIMELINE
// em WhyLlmProjectMapper.tsx (30 fps).
//
// Para usar audio local: baixe SFX free de pixabay/freesound em assets/sfx/,
// importe via `staticFile()` no WhyLlmProjectMapper.tsx e adicione `<Audio>`
// dentro de `<Sequence from={cue.from}>`.

export type SfxCue = {
  fromFrame: number;
  scene: string;
  type: "typing" | "pop" | "whoosh" | "ding";
  volume: number;
};

export const SFX_CUES: SfxCue[] = [
  { fromFrame: 150, scene: "PainTyping", type: "typing", volume: 0.35 },
  { fromFrame: 450, scene: "PainList", type: "pop", volume: 0.45 },
  { fromFrame: 690, scene: "Reveal", type: "whoosh", volume: 0.5 },
  { fromFrame: 870, scene: "Anatomy", type: "pop", volume: 0.4 },
  { fromFrame: 1230, scene: "SideBySide", type: "whoosh", volume: 0.4 },
  { fromFrame: 1770, scene: "Productivity", type: "ding", volume: 0.45 },
  { fromFrame: 2010, scene: "MultiAgent", type: "pop", volume: 0.4 },
  { fromFrame: 2250, scene: "CTA", type: "ding", volume: 0.55 },
];
