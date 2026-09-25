import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { useWhyT } from "../LangContext";
import { theme } from "../../theme";

export const Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useWhyT().hook;

  const line1P = spring({
    frame: frame - 4,
    fps,
    config: { damping: 14, stiffness: 130 },
  });
  const line2P = spring({
    frame: frame - 24,
    fps,
    config: { damping: 12, stiffness: 120 },
  });
  const subP = spring({
    frame: frame - 50,
    fps,
    config: { damping: 16, stiffness: 140 },
  });

  const cursorBlink = Math.floor(frame / 15) % 2 === 0 ? 1 : 0;

  return (
    <AbsoluteFill style={{ background: "#05060d" }}>
      <AbsoluteFill
        style={{
          alignItems: "center",
          justifyContent: "center",
          padding: 120,
          textAlign: "center",
        }}
      >
        <div
          style={{
            opacity: line1P,
            transform: `translateY(${interpolate(line1P, [0, 1], [30, 0])}px)`,
            fontFamily: theme.fonts.heading,
            fontWeight: 800,
            fontSize: 92,
            color: theme.colors.text,
            lineHeight: 1.05,
            letterSpacing: -2,
            marginBottom: 12,
          }}
        >
          {t.line1}
        </div>
        <div
          style={{
            opacity: line2P,
            transform: `translateY(${interpolate(line2P, [0, 1], [30, 0])}px)`,
            fontFamily: theme.fonts.heading,
            fontWeight: 900,
            fontSize: 110,
            letterSpacing: -3,
            background: `linear-gradient(120deg, ${theme.colors.red}, ${theme.colors.accent3})`,
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            lineHeight: 1.05,
          }}
        >
          {t.line2}
          <span
            style={{
              display: "inline-block",
              width: 12,
              height: 100,
              background: theme.colors.red,
              opacity: cursorBlink,
              marginLeft: 12,
              verticalAlign: "middle",
            }}
          />
        </div>
        <div
          style={{
            opacity: subP * 0.85,
            transform: `translateY(${interpolate(subP, [0, 1], [20, 0])}px)`,
            marginTop: 48,
            fontFamily: theme.fonts.mono,
            fontSize: 26,
            color: theme.colors.textMuted,
            maxWidth: 1100,
          }}
        >
          {t.sub}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
