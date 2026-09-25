import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { BackgroundFX } from "../components/BackgroundFX";
import { useT } from "../LangContext";
import { theme } from "../theme";

export const Intro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useT().intro;

  const titleP = spring({
    frame: frame - 8,
    fps,
    config: { damping: 14, stiffness: 100 },
  });
  const subP = spring({
    frame: frame - 28,
    fps,
    config: { damping: 16, stiffness: 110 },
  });
  const badgeP = spring({
    frame: frame - 50,
    fps,
    config: { damping: 18, stiffness: 130 },
  });

  const ringRot = (frame * 1.2) % 360;
  const ringScale = interpolate(
    spring({ frame, fps, config: { damping: 20, stiffness: 80 } }),
    [0, 1],
    [0.4, 1],
  );

  return (
    <AbsoluteFill>
      <BackgroundFX variant="purple" />

      <AbsoluteFill
        style={{
          alignItems: "center",
          justifyContent: "center",
          padding: 80,
        }}
      >
        {/* Logo orbit */}
        <div
          style={{
            position: "relative",
            width: 280,
            height: 280,
            marginBottom: 36,
            transform: `scale(${ringScale})`,
          }}
        >
          <svg
            width="280"
            height="280"
            style={{
              position: "absolute",
              transform: `rotate(${ringRot}deg)`,
              filter: `drop-shadow(0 0 20px ${theme.colors.accent}88)`,
            }}
          >
            <circle
              cx="140"
              cy="140"
              r="120"
              fill="none"
              stroke={theme.colors.accent}
              strokeWidth="2"
              strokeDasharray="6 12"
            />
            <circle
              cx="140"
              cy="140"
              r="90"
              fill="none"
              stroke={theme.colors.accent2}
              strokeWidth="1.5"
              strokeDasharray="3 8"
              opacity="0.7"
            />
          </svg>
          <svg
            width="280"
            height="280"
            style={{
              position: "absolute",
              transform: `rotate(${-ringRot * 0.7}deg)`,
            }}
          >
            <circle
              cx="140"
              cy="140"
              r="60"
              fill="none"
              stroke={theme.colors.accent3}
              strokeWidth="1"
              strokeDasharray="2 6"
            />
          </svg>
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 110,
              filter: `drop-shadow(0 0 30px ${theme.colors.accent})`,
            }}
          >
            <span
              style={{
                background: `linear-gradient(135deg, ${theme.colors.accent}, ${theme.colors.accent2})`,
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                fontFamily: theme.fonts.heading,
                fontWeight: 900,
                fontSize: 100,
              }}
            >
              ⚡
            </span>
          </div>
        </div>

        <div
          style={{
            opacity: titleP,
            transform: `translateY(${interpolate(titleP, [0, 1], [40, 0])}px)`,
            fontFamily: theme.fonts.heading,
            fontWeight: 900,
            fontSize: 110,
            letterSpacing: -3,
            textAlign: "center",
            background: `linear-gradient(120deg, #fff, ${theme.colors.accent2}, ${theme.colors.accent3})`,
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            marginBottom: 20,
            lineHeight: 1,
          }}
        >
          {t.title}
        </div>

        <div
          style={{
            opacity: subP,
            transform: `translateY(${interpolate(subP, [0, 1], [25, 0])}px)`,
            fontFamily: theme.fonts.heading,
            fontWeight: 500,
            fontSize: 36,
            color: theme.colors.textMuted,
            textAlign: "center",
            maxWidth: 1100,
            lineHeight: 1.3,
          }}
        >
          {t.taglinePre}
          <b style={{ color: theme.colors.text }}>{t.taglineMid}</b>
          <br />
          {t.taglinePost.split("llm-project-mapper")[0]}
          <code style={{ color: theme.colors.accent2 }}>llm-project-mapper</code>
        </div>

        <div
          style={{
            marginTop: 50,
            opacity: badgeP,
            transform: `scale(${interpolate(badgeP, [0, 1], [0.8, 1])})`,
            display: "flex",
            gap: 14,
          }}
        >
          {["Claude Code", "Codex", "Copilot", "Cursor", "Aider"].map((name, i) => (
            <div
              key={name}
              style={{
                padding: "10px 18px",
                borderRadius: 999,
                background: "rgba(255,255,255,0.08)",
                border: "1px solid rgba(255,255,255,0.15)",
                backdropFilter: "blur(8px)",
                color: theme.colors.text,
                fontFamily: theme.fonts.mono,
                fontSize: 18,
                fontWeight: 500,
                opacity: interpolate(badgeP, [0, 1], [0, 1]),
                transform: `translateY(${interpolate(
                  spring({
                    frame: frame - 50 - i * 4,
                    fps,
                    config: { damping: 18, stiffness: 160 },
                  }),
                  [0, 1],
                  [20, 0],
                )}px)`,
              }}
            >
              {name}
            </div>
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
