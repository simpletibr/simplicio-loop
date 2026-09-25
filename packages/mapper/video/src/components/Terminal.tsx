import React from "react";
import {
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { theme } from "../theme";

type Line =
  | { type: "prompt"; text: string }
  | { type: "out"; text: string; color?: string }
  | { type: "ok"; text: string }
  | { type: "err"; text: string };

type Props = {
  title?: string;
  lines: Line[];
  delay?: number;
  width?: number | string;
  charsPerFrame?: number;
};

export const Terminal: React.FC<Props> = ({
  title = "bash — llm-project-mapper",
  lines,
  delay = 0,
  width = 900,
  charsPerFrame = 2.4,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({
    frame: frame - delay,
    fps,
    config: { damping: 16, stiffness: 110 },
  });

  let charBudget = Math.max(0, (frame - delay - 8) * charsPerFrame);

  return (
    <div
      style={{
        width,
        opacity: enter,
        transform: `translateY(${interpolate(enter, [0, 1], [30, 0])}px)`,
        background: "#0a0e1a",
        borderRadius: 14,
        border: "1px solid #1f2a44",
        overflow: "hidden",
        boxShadow: "0 24px 60px rgba(0,0,0,0.5)",
        fontFamily: theme.fonts.mono,
      }}
    >
      <div
        style={{
          background: "#0e1424",
          padding: "10px 14px",
          display: "flex",
          alignItems: "center",
          gap: 8,
          borderBottom: "1px solid #1f2a44",
        }}
      >
        <Dot color="#ff5f56" />
        <Dot color="#ffbd2e" />
        <Dot color="#27c93f" />
        <div
          style={{
            marginLeft: 12,
            fontSize: 13,
            color: "#94a3b8",
          }}
        >
          {title}
        </div>
      </div>
      <div style={{ padding: "20px 22px", minHeight: 200 }}>
        {lines.map((line, i) => {
          const full = line.text;
          const remaining = charBudget;
          const visible = Math.max(0, Math.min(full.length, remaining));
          charBudget -= full.length + 4;
          const showCursor =
            visible < full.length && remaining > 0 && remaining < full.length + 4;
          const text = full.slice(0, Math.floor(visible));

          const colors = {
            prompt: theme.colors.text,
            out: line.type === "out" ? line.color ?? "#cbd5e1" : "#cbd5e1",
            ok: theme.colors.green,
            err: theme.colors.red,
          };
          const color = colors[line.type];

          return (
            <div
              key={i}
              style={{
                fontSize: 20,
                lineHeight: 1.55,
                color,
                whiteSpace: "pre-wrap",
              }}
            >
              {line.type === "prompt" && (
                <span style={{ color: theme.colors.accent2, marginRight: 8 }}>
                  $
                </span>
              )}
              {line.type === "ok" && (
                <span style={{ color: theme.colors.green, marginRight: 8 }}>
                  ✓
                </span>
              )}
              {line.type === "err" && (
                <span style={{ color: theme.colors.red, marginRight: 8 }}>
                  ✗
                </span>
              )}
              {text}
              {showCursor && <Cursor />}
            </div>
          );
        })}
      </div>
    </div>
  );
};

const Cursor: React.FC = () => {
  const frame = useCurrentFrame();
  const blink = Math.floor(frame / 12) % 2 === 0 ? 1 : 0.1;
  return (
    <span
      style={{
        display: "inline-block",
        width: 10,
        height: 22,
        background: "#e2e8f0",
        marginLeft: 2,
        verticalAlign: "middle",
        opacity: blink,
      }}
    />
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
