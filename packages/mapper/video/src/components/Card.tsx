import React from "react";
import {
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { theme } from "../theme";

type Props = {
  delay?: number;
  width?: number | string;
  padding?: number | string;
  glow?: string;
  children?: React.ReactNode;
  style?: React.CSSProperties;
};

export const Card: React.FC<Props> = ({
  delay = 0,
  width = 880,
  padding = 36,
  glow = theme.colors.accent,
  children,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const local = frame - delay;
  const p = spring({
    frame: local,
    fps,
    config: { damping: 14, stiffness: 100 },
  });
  const ty = interpolate(p, [0, 1], [40, 0]);

  return (
    <div
      style={{
        width,
        padding,
        borderRadius: 24,
        background:
          "linear-gradient(160deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.02) 100%)",
        border: "1px solid rgba(255,255,255,0.10)",
        backdropFilter: "blur(14px)",
        boxShadow: `0 20px 60px ${glow}33, inset 0 1px 0 rgba(255,255,255,0.08)`,
        opacity: p,
        transform: `translateY(${ty}px)`,
        color: theme.colors.text,
        fontFamily: theme.fonts.heading,
        ...style,
      }}
    >
      {children}
    </div>
  );
};
