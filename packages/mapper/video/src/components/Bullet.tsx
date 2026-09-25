import React from "react";
import {
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { theme } from "../theme";

type Props = {
  index?: number;
  delay?: number;
  icon?: string;
  title: string;
  text?: string;
  color?: string;
};

export const Bullet: React.FC<Props> = ({
  index = 0,
  delay = 0,
  icon = "•",
  title,
  text,
  color = theme.colors.accent,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const local = frame - delay - index * 6;
  const p = spring({
    frame: local,
    fps,
    config: { damping: 14, stiffness: 110 },
  });
  const tx = interpolate(p, [0, 1], [-30, 0]);

  return (
    <div
      style={{
        display: "flex",
        gap: 18,
        alignItems: "flex-start",
        opacity: p,
        transform: `translateX(${tx}px)`,
        marginBottom: 18,
      }}
    >
      <div
        style={{
          width: 48,
          height: 48,
          flexShrink: 0,
          borderRadius: 12,
          background: `linear-gradient(135deg, ${color}, ${color}66)`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 24,
          fontWeight: 800,
          color: "#fff",
          boxShadow: `0 8px 24px ${color}66`,
        }}
      >
        {icon}
      </div>
      <div style={{ paddingTop: 4 }}>
        <div
          style={{
            fontFamily: theme.fonts.heading,
            fontSize: 26,
            fontWeight: 700,
            color: theme.colors.text,
            marginBottom: 4,
          }}
        >
          {title}
        </div>
        {text && (
          <div
            style={{
              fontFamily: theme.fonts.heading,
              fontSize: 20,
              color: theme.colors.textMuted,
              lineHeight: 1.4,
              maxWidth: 760,
            }}
          >
            {text}
          </div>
        )}
      </div>
    </div>
  );
};
