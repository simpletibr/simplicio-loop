import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { BackgroundFX } from "../components/BackgroundFX";
import { AnimatedText } from "../components/AnimatedText";
import { Card } from "../components/Card";
import { useT } from "../LangContext";
import { theme } from "../theme";

export const WhatAreSkills: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useT().whatAreSkills;

  const cardP = spring({ frame: frame - 30, fps, config: { damping: 15, stiffness: 100 } });
  const pillsP = spring({ frame: frame - 60, fps, config: { damping: 15, stiffness: 100 } });

  return (
    <AbsoluteFill>
      <BackgroundFX variant="cyan" />
      <AbsoluteFill style={{ padding: "100px 120px", flexDirection: "column", gap: 32 }}>
        <div>
          <div
            style={{
              fontFamily: theme.fonts.mono,
              fontSize: 22,
              color: theme.colors.accent2,
              letterSpacing: 4,
              marginBottom: 8,
              textTransform: "uppercase",
            }}
          >
            {t.overline}
          </div>
          <AnimatedText text={t.title} size={88} align="left" gradient />
        </div>

        <div style={{ display: "flex", gap: 28, alignItems: "flex-start" }}>
          <Card delay={20} width={780} glow={theme.colors.accent2}>
            <div style={{ fontSize: 32, fontWeight: 700, marginBottom: 16, color: theme.colors.accent2 }}>
              {t.cardTitle}
            </div>
            <div style={{ fontSize: 28, lineHeight: 1.5, color: theme.colors.text }}>
              {t.cardBody[0]}
              <b>{t.cardBody[1]}</b>
              {t.cardBody[2]}
              <b>{t.cardBody[3]}</b>
              {t.cardBody[4]}
            </div>
            <div
              style={{
                marginTop: 22,
                padding: "16px 20px",
                background: "rgba(34, 211, 238, 0.10)",
                border: "1px solid rgba(34, 211, 238, 0.3)",
                borderRadius: 14,
                fontFamily: theme.fonts.mono,
                fontSize: 20,
                color: theme.colors.text,
              }}
            >
              <span style={{ color: theme.colors.accent2 }}>📁</span>{"  "}
              <code>{t.pathLabel}</code>
            </div>
          </Card>

          <div
            style={{
              opacity: cardP,
              transform: `translateY(${interpolate(cardP, [0, 1], [40, 0])}px) rotate(-3deg)`,
              flex: 1,
            }}
          >
            <SkillPaper paper={t.paper} />
          </div>
        </div>

        <div
          style={{
            display: "flex",
            gap: 18,
            opacity: pillsP,
            transform: `translateY(${interpolate(pillsP, [0, 1], [40, 0])}px)`,
          }}
        >
          {[
            { icon: "🎯", title: t.pillTitles[0], text: t.pillBodies[0] },
            { icon: "📝", title: t.pillTitles[1], text: t.pillBodies[1] },
            { icon: "✅", title: t.pillTitles[2], text: t.pillBodies[2] },
          ].map((c, i) => (
            <Pill key={c.title} delay={60 + i * 8} {...c} />
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Pill: React.FC<{
  delay: number;
  icon: string;
  title: string;
  text: string;
}> = ({ delay, icon, title, text }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 15, stiffness: 110 } });
  return (
    <div
      style={{
        flex: 1,
        padding: "20px 24px",
        borderRadius: 18,
        background: "rgba(255,255,255,0.05)",
        border: "1px solid rgba(255,255,255,0.10)",
        backdropFilter: "blur(8px)",
        opacity: p,
        transform: `translateY(${interpolate(p, [0, 1], [25, 0])}px) scale(${interpolate(p, [0, 1], [0.94, 1])})`,
      }}
    >
      <div style={{ fontSize: 36, marginBottom: 6 }}>{icon}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: theme.colors.text }}>{title}</div>
      <div style={{ fontSize: 18, color: theme.colors.textMuted, marginTop: 4 }}>{text}</div>
    </div>
  );
};

type PaperStrings = {
  descValue: string;
  triggerExample: string;
  step1: string;
  step2: string;
  dodItem: string;
};

const SkillPaper: React.FC<{ paper: PaperStrings }> = ({ paper }) => {
  return (
    <div
      style={{
        background: "#fefcf6",
        borderRadius: 14,
        padding: "28px 30px",
        boxShadow: "0 30px 70px rgba(0,0,0,0.5), 0 0 0 1px rgba(0,0,0,0.05)",
        fontFamily: theme.fonts.mono,
        color: "#1f2937",
        width: 380,
        position: "relative",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: -10,
          right: 22,
          width: 80,
          height: 22,
          background: "#fde68a",
          opacity: 0.85,
          borderRadius: 2,
          boxShadow: "0 6px 14px rgba(0,0,0,0.15)",
        }}
      />
      <div style={{ fontSize: 14, color: "#9ca3af", marginBottom: 8 }}>--- frontmatter ---</div>
      <div style={{ fontSize: 18 }}>
        <span style={{ color: "#7c3aed" }}>name</span>: playwright-e2e
      </div>
      <div style={{ fontSize: 16, marginTop: 4 }}>
        <span style={{ color: "#7c3aed" }}>description</span>:{" "}
        <span style={{ color: "#059669" }}>{paper.descValue}</span>
      </div>
      <div style={{ height: 1, background: "#e5e7eb", margin: "16px 0" }} />
      <div style={{ fontSize: 18, fontWeight: 700, color: "#111827" }}># Trigger</div>
      <div style={{ fontSize: 14, color: "#4b5563", marginTop: 4 }}>{paper.triggerExample}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: "#111827", marginTop: 12 }}># Steps</div>
      <div style={{ fontSize: 14, color: "#4b5563", marginTop: 4 }}>{paper.step1}</div>
      <div style={{ fontSize: 14, color: "#4b5563" }}>{paper.step2}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: "#111827", marginTop: 12 }}># Definition of Done</div>
      <div style={{ fontSize: 14, color: "#4b5563", marginTop: 4 }}>{paper.dodItem}</div>
    </div>
  );
};
