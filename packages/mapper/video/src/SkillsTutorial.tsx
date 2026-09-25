import React from "react";
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { Intro } from "./scenes/Intro";
import { WhatAreSkills } from "./scenes/WhatAreSkills";
import { Catalog } from "./scenes/Catalog";
import { PlaywrightSkill } from "./scenes/PlaywrightSkill";
import { CommitsSkill } from "./scenes/CommitsSkill";
import { HowToInvoke } from "./scenes/HowToInvoke";
import { CreateYourOwn } from "./scenes/CreateYourOwn";
import { BestPractices } from "./scenes/BestPractices";
import { Outro } from "./scenes/Outro";
import { SceneTransition } from "./components/SceneTransition";
import { LangProvider, useT } from "./LangContext";
import { Lang } from "./i18n";
import { theme } from "./theme";

const SCENES = [
  { Component: Intro, duration: 150 },
  { Component: WhatAreSkills, duration: 180 },
  { Component: Catalog, duration: 180 },
  { Component: PlaywrightSkill, duration: 240 },
  { Component: CommitsSkill, duration: 240 },
  { Component: HowToInvoke, duration: 210 },
  { Component: CreateYourOwn, duration: 210 },
  { Component: BestPractices, duration: 180 },
  { Component: Outro, duration: 180 },
] as const;

type Timed = {
  Component: React.FC;
  duration: number;
  from: number;
};

const TIMELINE: Timed[] = SCENES.reduce<Timed[]>((acc, s) => {
  const from = acc.length === 0 ? 0 : acc[acc.length - 1].from + acc[acc.length - 1].duration;
  acc.push({ Component: s.Component, duration: s.duration, from });
  return acc;
}, []);

export const TOTAL_DURATION = TIMELINE.reduce((sum, t) => sum + t.duration, 0);

export type SkillsTutorialProps = {
  language: Lang;
};

export const SkillsTutorial: React.FC<SkillsTutorialProps> = ({ language }) => {
  return (
    <LangProvider lang={language}>
      <AbsoluteFill style={{ background: theme.colors.bgFrom }}>
        {TIMELINE.map((t, i) => {
          const Comp = t.Component;
          return (
            <Sequence key={i} from={t.from} durationInFrames={t.duration}>
              <SceneTransition durationInFrames={t.duration}>
                <Comp />
              </SceneTransition>
            </Sequence>
          );
        })}
        <ProgressBar />
        <SceneLabel />
      </AbsoluteFill>
    </LangProvider>
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
  const t = useT();
  const activeIndex = TIMELINE.findIndex(
    (s) => frame >= s.from && frame < s.from + s.duration,
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
