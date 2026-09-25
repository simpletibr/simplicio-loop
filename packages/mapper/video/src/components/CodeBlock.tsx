import React from "react";
import {
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { theme } from "../theme";

type Token = { text: string; color?: string };

type Props = {
  title?: string;
  lines: Array<Token[] | string>;
  delay?: number;
  width?: number | string;
  fontSize?: number;
  highlight?: number[];
};

const palette = {
  keyword: "#c084fc",
  string: "#86efac",
  fn: "#7dd3fc",
  comment: "#64748b",
  punct: "#cbd5e1",
  type: "#f0abfc",
  number: "#fde68a",
  flag: "#fca5a5",
  prompt: "#22d3ee",
  text: "#e2e8f0",
};

export const CodeBlock: React.FC<Props> = ({
  title,
  lines,
  delay = 0,
  width = 920,
  fontSize = 22,
  highlight = [],
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({
    frame: frame - delay,
    fps,
    config: { damping: 15, stiffness: 120 },
  });

  return (
    <div
      style={{
        width,
        opacity: enter,
        transform: `translateY(${interpolate(enter, [0, 1], [30, 0])}px)`,
        borderRadius: 18,
        overflow: "hidden",
        background: theme.colors.code,
        border: `1px solid ${theme.colors.codeBorder}`,
        boxShadow: "0 24px 60px rgba(0,0,0,0.45)",
        fontFamily: theme.fonts.mono,
      }}
    >
      <div
        style={{
          background: "#0b1224",
          padding: "10px 16px",
          display: "flex",
          alignItems: "center",
          gap: 10,
          borderBottom: `1px solid ${theme.colors.codeBorder}`,
        }}
      >
        <Dot color="#ff5f56" />
        <Dot color="#ffbd2e" />
        <Dot color="#27c93f" />
        {title && (
          <div
            style={{
              marginLeft: 14,
              fontFamily: theme.fonts.mono,
              fontSize: 14,
              color: "#94a3b8",
            }}
          >
            {title}
          </div>
        )}
      </div>
      <div style={{ padding: "18px 22px" }}>
        {lines.map((line, i) => {
          const local = frame - delay - 6 - i * 3;
          const lp = spring({
            frame: local,
            fps,
            config: { damping: 18, stiffness: 140 },
          });
          const tokens: Token[] = Array.isArray(line)
            ? line
            : [{ text: line, color: palette.text }];
          const isHl = highlight.includes(i);
          return (
            <div
              key={i}
              style={{
                opacity: lp,
                transform: `translateX(${interpolate(lp, [0, 1], [-12, 0])}px)`,
                fontSize,
                lineHeight: 1.6,
                background: isHl ? "rgba(124, 92, 255, 0.16)" : undefined,
                borderLeft: isHl
                  ? `3px solid ${theme.colors.accent}`
                  : "3px solid transparent",
                padding: "2px 8px",
                borderRadius: 6,
                whiteSpace: "pre",
              }}
            >
              {tokens.map((t, j) => (
                <span key={j} style={{ color: t.color ?? palette.text }}>
                  {t.text}
                </span>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
};

const Dot: React.FC<{ color: string }> = ({ color }) => (
  <div
    style={{
      width: 12,
      height: 12,
      borderRadius: "50%",
      background: color,
    }}
  />
);

export const c = palette;
