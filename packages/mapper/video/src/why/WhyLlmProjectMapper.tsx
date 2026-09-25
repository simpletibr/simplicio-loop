import React from "react";
import {
  type Caption,
  createTikTokStyleCaptions,
  type TikTokPage,
} from "@remotion/captions";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Hook } from "./scenes/Hook";
import { PainTyping } from "./scenes/PainTyping";
import { PainList } from "./scenes/PainList";
import { Reveal } from "./scenes/Reveal";
import { Anatomy } from "./scenes/Anatomy";
import { SideBySide } from "./scenes/SideBySide";
import { Productivity } from "./scenes/Productivity";
import { MultiAgent } from "./scenes/MultiAgent";
import { CTA } from "./scenes/CTA";
import { SceneTransition } from "../components/SceneTransition";
import { WhyLangProvider, useWhyT } from "./LangContext";
import { Lang } from "./i18n";
import { theme } from "../theme";
import narration from "./narration.json";

const FPS = 30;
const CAPTION_PAGE_WINDOW_MS = 1400;

const SCENE_COMPONENTS = {
  hook: Hook,
  painTyping: PainTyping,
  painList: PainList,
  reveal: Reveal,
  anatomy: Anatomy,
  sideBySide: SideBySide,
  productivity: Productivity,
  multiAgent: MultiAgent,
  cta: CTA,
} as const;

type Timed = {
  Component: React.FC;
  durationInFrames: number;
  from: number;
  id: keyof typeof SCENE_COMPONENTS;
};

const TIMELINE: Timed[] = narration.timeline.map((scene) => ({
  id: scene.id as keyof typeof SCENE_COMPONENTS,
  Component: SCENE_COMPONENTS[scene.id as keyof typeof SCENE_COMPONENTS],
  durationInFrames: scene.durationInFrames,
  from: scene.fromFrame,
}));

const WHY_CAPTION_PAGES: Record<Lang, TikTokPage[]> = {
  pt: buildCaptionPages("pt"),
  en: buildCaptionPages("en"),
};

export const WHY_TOTAL_DURATION = TIMELINE.reduce(
  (sum, t) => sum + t.durationInFrames,
  0,
);

function buildCaptionPages(language: Lang) {
  const captions: Caption[] = narration.timeline.map((cue, index) => ({
    text: narration.tracks[language].cues[index],
    startMs: Math.round((cue.fromFrame / FPS) * 1000),
    endMs: Math.round(((cue.fromFrame + cue.durationInFrames) / FPS) * 1000),
    timestampMs: null,
    confidence: null,
  }));

  return createTikTokStyleCaptions({
    captions,
    combineTokensWithinMilliseconds: CAPTION_PAGE_WINDOW_MS,
  }).pages;
}

export type WhyLlmProjectMapperProps = {
  language: Lang;
};

export const WhyLlmProjectMapper: React.FC<WhyLlmProjectMapperProps> = ({
  language,
}) => {
  const voiceTrack = narration.tracks[language];
  return (
    <WhyLangProvider lang={language}>
      <AbsoluteFill style={{ background: theme.colors.bgFrom }}>
        {TIMELINE.map((t, i) => {
          const Comp = t.Component;
          return (
            <Sequence key={i} from={t.from} durationInFrames={t.durationInFrames}>
              <SceneTransition durationInFrames={t.durationInFrames}>
                <Comp />
              </SceneTransition>
            </Sequence>
          );
        })}
        <Audio src={staticFile(voiceTrack.output)} volume={1} />
        <Audio src={staticFile("sfx/rock-bg.mp3")} volume={0.15} />
        <ProgressBar />
        <SceneLabel />
        <RemotionCaptions language={language} />
      </AbsoluteFill>
    </WhyLangProvider>
  );
};

const ProgressBar: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const progress = Math.min(1, frame / durationInFrames);
  return (
    <div
      style={{
        position: "absolute",
        bottom: 0,
        left: 0,
        height: 4,
        width: `${progress * 100}%`,
        background: `linear-gradient(90deg, ${theme.colors.accent2}, ${theme.colors.accent3}, ${theme.colors.accent})`,
        boxShadow: `0 0 18px ${theme.colors.accent2}`,
      }}
    />
  );
};

const SceneLabel: React.FC = () => {
  const frame = useCurrentFrame();
  const t = useWhyT();
  const activeIndex = TIMELINE.findIndex(
    (s) => frame >= s.from && frame < s.from + s.durationInFrames,
  );
  const active = activeIndex === -1 ? 0 : activeIndex;
  return (
    <div
      style={{
        position: "absolute",
        top: 30,
        right: 40,
        padding: "8px 16px",
        borderRadius: 999,
        background: "rgba(0,0,0,0.35)",
        border: "1px solid rgba(255,255,255,0.12)",
        backdropFilter: "blur(10px)",
        fontFamily: theme.fonts.mono,
        fontSize: 14,
        color: theme.colors.textMuted,
        letterSpacing: 2,
      }}
    >
      <span style={{ color: theme.colors.accent2 }}>
        {String(active + 1).padStart(2, "0")}
      </span>
      <span style={{ margin: "0 8px", opacity: 0.4 }}>/</span>
      <span>{String(TIMELINE.length).padStart(2, "0")}</span>
      <span style={{ margin: "0 12px", opacity: 0.4 }}>·</span>
      <span style={{ color: theme.colors.text }}>{t.sceneLabels[active]}</span>
    </div>
  );
};

const RemotionCaptions: React.FC<{language: Lang}> = ({language}) => {
  const { fps, durationInFrames } = useVideoConfig();
  const pages = WHY_CAPTION_PAGES[language];

  return (
    <>
      {pages.map((page, index) => {
        const pageStartFrame = Math.round((page.startMs / 1000) * fps);
        const fallbackEndMs = Math.round((durationInFrames / fps) * 1000);
        const nextStartMs = pages[index + 1]?.startMs ?? fallbackEndMs;
        const pageEndMs = Math.max(
          page.tokens[page.tokens.length - 1]?.toMs ?? page.startMs,
          nextStartMs,
        );
        const pageDurationInFrames =
          Math.max(1, Math.round((pageEndMs / 1000) * fps) - pageStartFrame);

        return (
          <Sequence
            key={`${language}-${page.startMs}`}
            from={pageStartFrame}
            durationInFrames={pageDurationInFrames}
          >
            <CaptionPage page={page} />
          </Sequence>
        );
      })}
    </>
  );
};

const CaptionPage: React.FC<{page: TikTokPage}> = ({page}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTimeMs = (frame / fps) * 1000;
  const absoluteTimeMs = page.startMs + currentTimeMs;

  return (
    <div
      style={{
        position: "absolute",
        left: 140,
        right: 140,
        bottom: 84,
        display: "flex",
        justifyContent: "center",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          maxWidth: 1240,
          padding: "18px 28px",
          borderRadius: 28,
          background: "rgba(5, 10, 24, 0.74)",
          border: "1px solid rgba(255,255,255,0.12)",
          boxShadow: "0 18px 48px rgba(0,0,0,0.24)",
          backdropFilter: "blur(16px)",
          color: theme.colors.text,
          fontFamily: theme.fonts.heading,
          fontSize: 36,
          lineHeight: 1.28,
          fontWeight: 600,
          textAlign: "center",
          whiteSpace: "pre-wrap",
        }}
      >
        {page.tokens.map((token) => {
          const isActive =
            token.fromMs <= absoluteTimeMs && token.toMs > absoluteTimeMs;
          return (
            <span
              key={`${token.fromMs}-${token.toMs}-${token.text}`}
              style={{
                color: isActive ? theme.colors.accent2 : theme.colors.text,
              }}
            >
              {token.text}
            </span>
          );
        })}
      </div>
    </div>
  );
};
