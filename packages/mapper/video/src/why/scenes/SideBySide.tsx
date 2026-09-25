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

export const SideBySide: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useWhyT().sideBySide;

  const overlineP = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 130 },
  });

  return (
    <AbsoluteFill>
      <BackgroundFX variant="dark" showOrbs={false} />

      <div
        style={{
          position: "absolute",
          top: 60,
          left: "50%",
          transform: "translateX(-50%)",
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
          flexDirection: "row",
          padding: "120px 60px 80px 60px",
          gap: 30,
        }}
      >
        <Pane
          title={t.leftTitle}
          chat={t.leftChat}
          accent={theme.colors.red}
          badge={t.leftBadge}
          startFrame={10}
          stepFrames={40}
          isBad
        />
        <Pane
          title={t.rightTitle}
          chat={t.rightChat}
          accent={theme.colors.green}
          badge={t.rightBadge}
          startFrame={20}
          stepFrames={40}
        />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

type PaneProps = {
  title: string;
  chat: Array<{ role: "user" | "ai"; text: string }>;
  accent: string;
  badge: string;
  startFrame: number;
  stepFrames: number;
  isBad?: boolean;
};

const Pane: React.FC<PaneProps> = ({
  title,
  chat,
  accent,
  badge,
  startFrame,
  stepFrames,
  isBad,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const titleP = spring({
    frame: frame - startFrame + 10,
    fps,
    config: { damping: 16, stiffness: 110 },
  });
  const badgeP = spring({
    frame: frame - (startFrame + chat.length * stepFrames),
    fps,
    config: { damping: 14, stiffness: 130 },
  });

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        padding: "30px 28px",
        borderRadius: 22,
        background: isBad
          ? "rgba(248,113,113,0.06)"
          : "rgba(52,211,153,0.06)",
        border: `1px solid ${accent}44`,
        gap: 18,
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          opacity: titleP,
          fontFamily: theme.fonts.heading,
          fontWeight: 800,
          fontSize: 34,
          color: accent,
          letterSpacing: -1,
          marginBottom: 6,
        }}
      >
        {title}
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 10,
          flex: 1,
          overflow: "hidden",
        }}
      >
        {chat.map((msg, i) => {
          const p = spring({
            frame: frame - startFrame - i * stepFrames,
            fps,
            config: { damping: 16, stiffness: 130 },
          });
          if (p <= 0) return null;
          const isUser = msg.role === "user";
          return (
            <div
              key={i}
              style={{
                alignSelf: isUser ? "flex-end" : "flex-start",
                maxWidth: "85%",
                padding: "10px 14px",
                borderRadius: 12,
                background: isUser
                  ? "rgba(124,92,255,0.18)"
                  : "rgba(255,255,255,0.06)",
                border: `1px solid ${
                  isUser ? theme.colors.accent + "66" : "rgba(255,255,255,0.12)"
                }`,
                fontFamily: theme.fonts.mono,
                fontSize: 17,
                color: theme.colors.text,
                lineHeight: 1.35,
                opacity: p,
                transform: `translateY(${interpolate(p, [0, 1], [12, 0])}px)`,
              }}
            >
              <span
                style={{
                  fontSize: 10,
                  letterSpacing: 1.5,
                  color: isUser ? theme.colors.accent2 : theme.colors.textMuted,
                  marginRight: 6,
                  textTransform: "uppercase",
                }}
              >
                {isUser ? "you" : "AI"}
              </span>
              {msg.text}
            </div>
          );
        })}
      </div>
      <div
        style={{
          alignSelf: "center",
          padding: "10px 22px",
          borderRadius: 999,
          background: accent + "33",
          border: `2px solid ${accent}`,
          fontFamily: theme.fonts.heading,
          fontSize: 22,
          fontWeight: 700,
          color: accent,
          letterSpacing: 0.5,
          opacity: badgeP,
          transform: `scale(${interpolate(badgeP, [0, 1], [0.7, 1])})`,
          marginTop: 8,
        }}
      >
        {badge}
      </div>
    </div>
  );
};
