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

export const Productivity: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useWhyT().productivity;

  const overlineP = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 150 },
  });
  const titleP = spring({
    frame: frame - 10,
    fps,
    config: { damping: 14, stiffness: 130 },
  });

  return (
    <AbsoluteFill>
      <BackgroundFX variant="purple" />

      <div
        style={{
          position: "absolute",
          top: 80,
          left: 120,
          opacity: overlineP,
          fontFamily: theme.fonts.mono,
          fontSize: 22,
          letterSpacing: 4,
          color: theme.colors.green,
          textTransform: "uppercase",
        }}
      >
        {t.overline}
      </div>

      <AbsoluteFill
        style={{
          alignItems: "center",
          justifyContent: "center",
          padding: "180px 120px",
          flexDirection: "column",
        }}
      >
        <div
          style={{
            opacity: titleP,
            transform: `translateY(${interpolate(titleP, [0, 1], [25, 0])}px)`,
            fontFamily: theme.fonts.heading,
            fontWeight: 800,
            fontSize: 64,
            color: theme.colors.text,
            marginBottom: 80,
            letterSpacing: -2,
            textAlign: "center",
          }}
        >
          {t.title}
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr 1fr",
            gap: 40,
            width: "100%",
            maxWidth: 1500,
          }}
        >
          {t.metrics.map((m, i) => {
            const p = spring({
              frame: frame - 30 - i * 25,
              fps,
              config: { damping: 10, stiffness: 110 },
            });
            return (
              <div
                key={i}
                style={{
                  textAlign: "center",
                  opacity: p,
                  transform: `translateY(${interpolate(p, [0, 1], [50, 0])}px) scale(${interpolate(p, [0, 1], [0.85, 1])})`,
                }}
              >
                <div
                  style={{
                    fontFamily: theme.fonts.heading,
                    fontWeight: 900,
                    fontSize: 140,
                    letterSpacing: -5,
                    lineHeight: 1,
                    background: `linear-gradient(120deg, ${theme.colors.green}, ${theme.colors.accent2})`,
                    WebkitBackgroundClip: "text",
                    WebkitTextFillColor: "transparent",
                    marginBottom: 20,
                  }}
                >
                  {m.value}
                </div>
                <div
                  style={{
                    fontFamily: theme.fonts.heading,
                    fontSize: 24,
                    color: theme.colors.textMuted,
                    lineHeight: 1.3,
                    maxWidth: 320,
                    margin: "0 auto",
                  }}
                >
                  {m.label}
                </div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
