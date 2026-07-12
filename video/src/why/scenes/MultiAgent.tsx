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

const AGENTS = [
  "Claude Code",
  "Codex",
  "Copilot",
  "Cursor",
  "Aider",
  "Simplicio Agent",
];

export const MultiAgent: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useWhyT().multiAgent;

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
  const centerP = spring({
    frame: frame - 30,
    fps,
    config: { damping: 12, stiffness: 120 },
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
          color: theme.colors.accent,
          textTransform: "uppercase",
        }}
      >
        {t.overline}
      </div>

      <AbsoluteFill
        style={{
          alignItems: "center",
          justifyContent: "center",
          padding: "180px 120px 140px 120px",
          flexDirection: "column",
        }}
      >
        <div
          style={{
            opacity: titleP,
            transform: `translateY(${interpolate(titleP, [0, 1], [25, 0])}px)`,
            fontFamily: theme.fonts.heading,
            fontWeight: 800,
            fontSize: 60,
            color: theme.colors.text,
            marginBottom: 50,
            textAlign: "center",
            letterSpacing: -2,
          }}
        >
          {t.title}
        </div>

        <div
          style={{
            position: "relative",
            width: 700,
            height: 500,
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              opacity: centerP,
              transform: `scale(${interpolate(centerP, [0, 1], [0.6, 1])})`,
            }}
          >
            <div
              style={{
                padding: "28px 44px",
                borderRadius: 22,
                background: `linear-gradient(135deg, ${theme.colors.accent}, ${theme.colors.accent2})`,
                fontFamily: theme.fonts.mono,
                fontSize: 40,
                fontWeight: 800,
                color: "#fff",
                boxShadow: `0 0 80px ${theme.colors.accent2}88, 0 0 30px ${theme.colors.accent}66`,
                letterSpacing: -1,
              }}
            >
              {t.centerLabel}
            </div>
          </div>
          {AGENTS.map((name, i) => {
            const angle = (i / AGENTS.length) * Math.PI * 2 - Math.PI / 2;
            const orbitAngle = angle + frame * 0.005;
            const radius = 280;
            const x = 350 + Math.cos(orbitAngle) * radius;
            const y = 250 + Math.sin(orbitAngle) * radius * 0.7;
            const p = spring({
              frame: frame - 50 - i * 8,
              fps,
              config: { damping: 12, stiffness: 150 },
            });
            return (
              <div
                key={name}
                style={{
                  position: "absolute",
                  left: x,
                  top: y,
                  transform: `translate(-50%, -50%) scale(${interpolate(p, [0, 1], [0.4, 1])})`,
                  opacity: p,
                  padding: "10px 18px",
                  borderRadius: 999,
                  background: "rgba(255,255,255,0.1)",
                  border: "1px solid rgba(255,255,255,0.2)",
                  backdropFilter: "blur(10px)",
                  fontFamily: theme.fonts.mono,
                  fontSize: 18,
                  fontWeight: 600,
                  color: theme.colors.text,
                  whiteSpace: "nowrap",
                }}
              >
                {name}
              </div>
            );
          })}
        </div>

        <div
          style={{
            position: "absolute",
            bottom: 60,
            left: 0,
            right: 0,
            textAlign: "center",
            opacity: 0.85,
            fontFamily: theme.fonts.heading,
            fontSize: 22,
            color: theme.colors.textMuted,
            padding: "0 200px",
          }}
        >
          {t.sub}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
