import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { BackgroundFX } from "../../components/BackgroundFX";
import { useWhyT } from "../LangContext";
import { theme } from "../../theme";

export const CTA: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useWhyT().cta;

  const titleP = spring({
    frame: frame - 4,
    fps,
    config: { damping: 14, stiffness: 130 },
  });
  const cmdP = spring({
    frame: frame - 25,
    fps,
    config: { damping: 12, stiffness: 150 },
  });
  const repoP = spring({
    frame: frame - 50,
    fps,
    config: { damping: 14, stiffness: 140 },
  });
  const footerP = spring({
    frame: frame - 70,
    fps,
    config: { damping: 16, stiffness: 150 },
  });

  return (
    <AbsoluteFill>
      <BackgroundFX variant="purple" />

      <AbsoluteFill
        style={{
          alignItems: "center",
          justifyContent: "center",
          padding: 100,
          flexDirection: "column",
          textAlign: "center",
        }}
      >
        <div
          style={{
            opacity: titleP,
            transform: `translateY(${interpolate(titleP, [0, 1], [30, 0])}px)`,
            fontFamily: theme.fonts.heading,
            fontWeight: 900,
            fontSize: 108,
            letterSpacing: -3,
            background: `linear-gradient(120deg, #fff, ${theme.colors.accent2}, ${theme.colors.accent3})`,
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            marginBottom: 60,
            lineHeight: 1,
          }}
        >
          {t.title}
        </div>

        <div
          style={{
            opacity: cmdP,
            transform: `translateY(${interpolate(cmdP, [0, 1], [25, 0])}px) scale(${interpolate(cmdP, [0, 1], [0.92, 1])})`,
            padding: "26px 42px",
            borderRadius: 16,
            background: theme.colors.code,
            border: `2px solid ${theme.colors.accent2}`,
            fontFamily: theme.fonts.mono,
            fontSize: 38,
            color: theme.colors.text,
            boxShadow: `0 0 50px ${theme.colors.accent2}55`,
            marginBottom: 40,
          }}
        >
          <span style={{ color: theme.colors.green }}>$</span>{" "}
          <span style={{ color: theme.colors.accent2 }}>{t.command}</span>
        </div>

        <div
          style={{
            opacity: repoP,
            transform: `translateY(${interpolate(repoP, [0, 1], [20, 0])}px)`,
            fontFamily: theme.fonts.mono,
            fontSize: 28,
            color: theme.colors.text,
            padding: "12px 24px",
            borderRadius: 999,
            background: "rgba(255,255,255,0.05)",
            border: "1px solid rgba(255,255,255,0.15)",
            marginBottom: 60,
          }}
        >
          ↗ {t.repo}
        </div>

        <div
          style={{
            opacity: footerP * 0.7,
            fontFamily: theme.fonts.heading,
            fontSize: 22,
            color: theme.colors.textMuted,
            letterSpacing: 0.5,
          }}
        >
          {t.footer}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
