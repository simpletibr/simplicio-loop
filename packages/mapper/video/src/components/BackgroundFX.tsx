import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate } from "remotion";
import { theme } from "../theme";

type Props = {
  variant?: "purple" | "cyan" | "pink" | "dark";
  showGrid?: boolean;
  showOrbs?: boolean;
};

export const BackgroundFX: React.FC<Props> = ({
  variant = "purple",
  showGrid = true,
  showOrbs = true,
}) => {
  const frame = useCurrentFrame();

  const palette = {
    purple: [theme.colors.bgFrom, theme.colors.bgTo, theme.colors.accent],
    cyan: ["#06121f", "#0b2a3a", theme.colors.accent2],
    pink: ["#1a0b2e", "#3b0a2a", theme.colors.accent3],
    dark: ["#05060d", "#0a0d18", "#1c1f3a"],
  }[variant];

  const orbA = {
    x: interpolate(Math.sin(frame / 60), [-1, 1], [10, 30]),
    y: interpolate(Math.cos(frame / 70), [-1, 1], [10, 30]),
    s: interpolate(Math.sin(frame / 90), [-1, 1], [0.9, 1.15]),
  };
  const orbB = {
    x: interpolate(Math.cos(frame / 50), [-1, 1], [60, 80]),
    y: interpolate(Math.sin(frame / 80), [-1, 1], [55, 80]),
    s: interpolate(Math.cos(frame / 100), [-1, 1], [0.85, 1.1]),
  };

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(1200px 700px at 30% 20%, ${palette[2]}33, transparent 60%), linear-gradient(135deg, ${palette[0]} 0%, ${palette[1]} 100%)`,
      }}
    >
      {showOrbs && (
        <>
          <div
            style={{
              position: "absolute",
              left: `${orbA.x}%`,
              top: `${orbA.y}%`,
              width: 520,
              height: 520,
              borderRadius: "50%",
              background: `radial-gradient(circle, ${palette[2]}55, transparent 70%)`,
              filter: "blur(40px)",
              transform: `translate(-50%, -50%) scale(${orbA.s})`,
            }}
          />
          <div
            style={{
              position: "absolute",
              left: `${orbB.x}%`,
              top: `${orbB.y}%`,
              width: 460,
              height: 460,
              borderRadius: "50%",
              background: `radial-gradient(circle, ${theme.colors.accent3}44, transparent 70%)`,
              filter: "blur(50px)",
              transform: `translate(-50%, -50%) scale(${orbB.s})`,
            }}
          />
        </>
      )}

      {showGrid && (
        <svg
          width="100%"
          height="100%"
          style={{ position: "absolute", inset: 0, opacity: 0.08 }}
        >
          <defs>
            <pattern
              id="grid"
              width="60"
              height="60"
              patternUnits="userSpaceOnUse"
            >
              <path
                d="M 60 0 L 0 0 0 60"
                fill="none"
                stroke={theme.colors.text}
                strokeWidth="1"
              />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" />
        </svg>
      )}

      <Particles />

      <AbsoluteFill
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 40%, rgba(0,0,0,0.45) 100%)",
          pointerEvents: "none",
        }}
      />
    </AbsoluteFill>
  );
};

const PARTICLES = Array.from({ length: 40 }, (_, i) => ({
  id: i,
  x: (i * 137.508) % 100,
  y: (i * 73.21) % 100,
  size: ((i * 13) % 5) + 2,
  speed: ((i * 7) % 6) + 3,
  hue: (i * 29) % 360,
}));

const Particles: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <>
      {PARTICLES.map((p) => {
        const dy = ((frame / p.speed) % 120) - 60;
        const opacity = interpolate(
          Math.sin(frame / (p.speed * 5) + p.id),
          [-1, 1],
          [0.15, 0.55],
        );
        return (
          <div
            key={p.id}
            style={{
              position: "absolute",
              left: `${p.x}%`,
              top: `calc(${p.y}% + ${dy}px)`,
              width: p.size,
              height: p.size,
              borderRadius: "50%",
              background: `hsl(${p.hue}, 80%, 70%)`,
              opacity,
              filter: "blur(1px)",
            }}
          />
        );
      })}
    </>
  );
};
