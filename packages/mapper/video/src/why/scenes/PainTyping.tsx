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

type Bubble = {
  role: "user" | "ai";
  text: string;
  fromFrame: number;
  highlight?: boolean;
};

export const PainTyping: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useWhyT().painTyping;

  const overlineP = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 130 },
  });

  const bubbles: Bubble[] = [
    { role: "user", text: t.user1, fromFrame: 10 },
    { role: "ai", text: t.ai1, fromFrame: 50 },
    { role: "user", text: t.user2, fromFrame: 90 },
    { role: "ai", text: t.ai2, fromFrame: 130, highlight: true },
  ];

  const annotationP = spring({
    frame: frame - 160,
    fps,
    config: { damping: 12, stiffness: 130 },
  });

  return (
    <AbsoluteFill>
      <BackgroundFX variant="dark" />

      <div
        style={{
          position: "absolute",
          top: 80,
          left: 120,
          opacity: overlineP,
          fontFamily: theme.fonts.mono,
          fontSize: 22,
          letterSpacing: 4,
          color: theme.colors.red,
          textTransform: "uppercase",
        }}
      >
        {t.overline}
      </div>

      <AbsoluteFill
        style={{
          alignItems: "center",
          justifyContent: "center",
          padding: "180px 180px 120px 180px",
        }}
      >
        <div
          style={{
            width: "100%",
            maxWidth: 1200,
            display: "flex",
            flexDirection: "column",
            gap: 18,
          }}
        >
          {bubbles.map((b, i) => {
            const p = spring({
              frame: frame - b.fromFrame,
              fps,
              config: { damping: 16, stiffness: 130 },
            });
            if (p <= 0) return null;
            const isUser = b.role === "user";
            return (
              <div
                key={i}
                style={{
                  alignSelf: isUser ? "flex-end" : "flex-start",
                  maxWidth: "75%",
                  padding: "18px 24px",
                  borderRadius: 18,
                  background: isUser
                    ? "rgba(124,92,255,0.18)"
                    : b.highlight
                      ? "rgba(248,113,113,0.18)"
                      : "rgba(255,255,255,0.06)",
                  border: `1px solid ${
                    isUser
                      ? theme.colors.accent + "55"
                      : b.highlight
                        ? theme.colors.red + "88"
                        : "rgba(255,255,255,0.12)"
                  }`,
                  fontFamily: theme.fonts.mono,
                  fontSize: 28,
                  color: theme.colors.text,
                  lineHeight: 1.4,
                  opacity: p,
                  transform: `translateY(${interpolate(p, [0, 1], [20, 0])}px)`,
                  boxShadow: b.highlight
                    ? `0 0 30px ${theme.colors.red}33`
                    : "none",
                }}
              >
                <div
                  style={{
                    fontSize: 14,
                    letterSpacing: 2,
                    color: isUser
                      ? theme.colors.accent2
                      : b.highlight
                        ? theme.colors.red
                        : theme.colors.textMuted,
                    marginBottom: 6,
                    textTransform: "uppercase",
                  }}
                >
                  {isUser ? "you" : "AI"}
                </div>
                {b.text}
              </div>
            );
          })}
        </div>
      </AbsoluteFill>

      <div
        style={{
          position: "absolute",
          bottom: 80,
          left: "50%",
          transform: `translateX(-50%) translateY(${interpolate(
            annotationP,
            [0, 1],
            [20, 0],
          )}px)`,
          opacity: annotationP,
          padding: "12px 24px",
          borderRadius: 12,
          background: theme.colors.red + "22",
          border: `2px solid ${theme.colors.red}`,
          fontFamily: theme.fonts.heading,
          fontSize: 26,
          fontWeight: 700,
          color: theme.colors.red,
          letterSpacing: 0.5,
        }}
      >
        {t.annotation}
      </div>
    </AbsoluteFill>
  );
};
