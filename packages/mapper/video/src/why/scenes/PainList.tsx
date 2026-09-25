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

export const PainList: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useWhyT().painList;

  const titleP = spring({
    frame: frame - 6,
    fps,
    config: { damping: 16, stiffness: 110 },
  });

  return (
    <AbsoluteFill>
      <BackgroundFX variant="pink" showOrbs />

      <div
        style={{
          position: "absolute",
          top: 80,
          left: 120,
          opacity: titleP,
          fontFamily: theme.fonts.mono,
          fontSize: 22,
          letterSpacing: 4,
          color: theme.colors.accent3,
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
        }}
      >
        <div
          style={{
            opacity: titleP,
            transform: `translateY(${interpolate(titleP, [0, 1], [30, 0])}px)`,
            fontFamily: theme.fonts.heading,
            fontWeight: 800,
            fontSize: 76,
            letterSpacing: -2,
            color: theme.colors.text,
            textAlign: "center",
            marginBottom: 64,
            lineHeight: 1.1,
          }}
        >
          {t.title}
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 28,
            maxWidth: 1400,
            width: "100%",
          }}
        >
          {t.items.map((item, i) => {
            const p = spring({
              frame: frame - 20 - i * 14,
              fps,
              config: { damping: 14, stiffness: 150 },
            });
            return (
              <div
                key={i}
                style={{
                  padding: "28px 32px",
                  borderRadius: 18,
                  background:
                    "linear-gradient(135deg, rgba(248,113,113,0.12), rgba(244,114,182,0.08))",
                  border: `1px solid ${theme.colors.red}55`,
                  display: "flex",
                  alignItems: "center",
                  gap: 20,
                  opacity: p,
                  transform: `translateX(${interpolate(p, [0, 1], [-30, 0])}px)`,
                  backdropFilter: "blur(8px)",
                }}
              >
                <div
                  style={{
                    fontSize: 48,
                    fontWeight: 900,
                    fontFamily: theme.fonts.heading,
                    color: theme.colors.red,
                    minWidth: 60,
                    textAlign: "center",
                  }}
                >
                  ×
                </div>
                <div
                  style={{
                    fontFamily: theme.fonts.heading,
                    fontSize: 28,
                    fontWeight: 600,
                    color: theme.colors.text,
                    lineHeight: 1.3,
                  }}
                >
                  {item}
                </div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
