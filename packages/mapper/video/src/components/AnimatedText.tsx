import React from "react";
import {
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { theme } from "../theme";

type Props = {
  text: string;
  delay?: number;
  size?: number;
  color?: string;
  weight?: number | string;
  letterSpacing?: number | string;
  align?: "left" | "center" | "right";
  font?: "heading" | "mono";
  shadow?: boolean;
  gradient?: boolean;
  byChar?: boolean;
};

export const AnimatedText: React.FC<Props> = ({
  text,
  delay = 0,
  size = 64,
  color = theme.colors.text,
  weight = 700,
  letterSpacing = -0.5,
  align = "center",
  font = "heading",
  shadow = true,
  gradient = false,
  byChar = true,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const baseStyle: React.CSSProperties = {
    fontFamily: theme.fonts[font],
    fontWeight: weight,
    fontSize: size,
    letterSpacing,
    textAlign: align,
    lineHeight: 1.1,
    color,
    textShadow: shadow ? "0 6px 30px rgba(0,0,0,0.5)" : undefined,
    background: gradient
      ? `linear-gradient(120deg, ${theme.colors.text} 0%, ${theme.colors.accent2} 50%, ${theme.colors.accent3} 100%)`
      : undefined,
    WebkitBackgroundClip: gradient ? "text" : undefined,
    WebkitTextFillColor: gradient ? "transparent" : undefined,
    backgroundClip: gradient ? "text" : undefined,
    display: "inline-block",
  };

  if (!byChar) {
    const local = frame - delay;
    const progress = spring({
      frame: local,
      fps,
      config: { damping: 14, stiffness: 110 },
    });
    return (
      <div
        style={{
          ...baseStyle,
          opacity: progress,
          transform: `translateY(${interpolate(progress, [0, 1], [22, 0])}px)`,
          width: "100%",
        }}
      >
        {text}
      </div>
    );
  }

  return (
    <div style={{ width: "100%", textAlign: align }}>
      {text.split("").map((ch, i) => {
        const local = frame - delay - i * 1.2;
        const p = spring({
          frame: local,
          fps,
          config: { damping: 12, stiffness: 130 },
        });
        const ty = interpolate(p, [0, 1], [40, 0]);
        const blur = interpolate(p, [0, 1], [10, 0]);
        return (
          <span
            key={i}
            style={{
              ...baseStyle,
              opacity: p,
              transform: `translateY(${ty}px)`,
              filter: `blur(${blur}px)`,
              whiteSpace: "pre",
            }}
          >
            {ch}
          </span>
        );
      })}
    </div>
  );
};
