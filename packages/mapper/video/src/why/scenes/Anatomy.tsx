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

export const Anatomy: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useWhyT().anatomy;

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
  const glueP = spring({
    frame: frame - 170,
    fps,
    config: { damping: 16, stiffness: 140 },
  });

  return (
    <AbsoluteFill>
      <BackgroundFX variant="cyan" />

      <div
        style={{
          position: "absolute",
          top: 80,
          left: 120,
          opacity: overlineP,
          fontFamily: theme.fonts.mono,
          fontSize: 22,
          letterSpacing: 4,
          color: theme.colors.accent2,
          textTransform: "uppercase",
        }}
      >
        {t.overline}
      </div>

      <AbsoluteFill
        style={{
          alignItems: "center",
          justifyContent: "center",
          padding: "160px 120px 200px 120px",
          flexDirection: "column",
        }}
      >
        <div
          style={{
            opacity: titleP,
            transform: `translateY(${interpolate(titleP, [0, 1], [30, 0])}px)`,
            fontFamily: theme.fonts.heading,
            fontWeight: 800,
            fontSize: 68,
            color: theme.colors.text,
            marginBottom: 56,
            textAlign: "center",
            letterSpacing: -2,
          }}
        >
          {t.title}
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 24,
            width: "100%",
            maxWidth: 1400,
          }}
        >
          {t.pieces.map((piece, i) => {
            const p = spring({
              frame: frame - 30 - i * 18,
              fps,
              config: { damping: 12, stiffness: 150 },
            });
            return (
              <div
                key={i}
                style={{
                  padding: "26px 32px",
                  borderRadius: 18,
                  background: "rgba(34,211,238,0.08)",
                  border: `1px solid ${theme.colors.accent2}55`,
                  opacity: p,
                  transform: `translateY(${interpolate(p, [0, 1], [40, 0])}px) scale(${interpolate(p, [0, 1], [0.92, 1])})`,
                  backdropFilter: "blur(10px)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                }}
              >
                <div
                  style={{
                    fontFamily: theme.fonts.mono,
                    fontSize: 32,
                    fontWeight: 700,
                    color: theme.colors.accent2,
                  }}
                >
                  {piece.label}
                </div>
                <div
                  style={{
                    fontFamily: theme.fonts.heading,
                    fontSize: 22,
                    color: theme.colors.text,
                    lineHeight: 1.4,
                    opacity: 0.92,
                  }}
                >
                  {piece.desc}
                </div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>

      <div
        style={{
          position: "absolute",
          bottom: 60,
          left: 0,
          right: 0,
          textAlign: "center",
          opacity: glueP * 0.92,
          transform: `translateY(${interpolate(glueP, [0, 1], [15, 0])}px)`,
          fontFamily: theme.fonts.heading,
          fontSize: 26,
          fontWeight: 500,
          color: theme.colors.text,
          letterSpacing: -0.5,
        }}
      >
        {t.glueLine}
      </div>
    </AbsoluteFill>
  );
};
