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

export const Reveal: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useWhyT().reveal;

  const preP = spring({
    frame: frame - 4,
    fps,
    config: { damping: 14, stiffness: 130 },
  });
  const brandP = spring({
    frame: frame - 28,
    fps,
    config: { damping: 11, stiffness: 110 },
  });
  const subP = spring({
    frame: frame - 65,
    fps,
    config: { damping: 16, stiffness: 140 },
  });

  const brandScale = interpolate(brandP, [0, 1], [0.5, 1]);
  const ringRot = frame * 1.5;

  return (
    <AbsoluteFill>
      <BackgroundFX variant="purple" />

      <AbsoluteFill
        style={{
          alignItems: "center",
          justifyContent: "center",
          padding: 80,
          textAlign: "center",
        }}
      >
        <div
          style={{
            opacity: preP,
            transform: `translateY(${interpolate(preP, [0, 1], [25, 0])}px)`,
            fontFamily: theme.fonts.heading,
            fontWeight: 500,
            fontSize: 44,
            color: theme.colors.textMuted,
            marginBottom: 36,
            letterSpacing: -0.5,
          }}
        >
          {t.pre}
        </div>

        <div
          style={{
            position: "relative",
            transform: `scale(${brandScale})`,
            opacity: brandP,
            marginBottom: 36,
          }}
        >
          <svg
            width="800"
            height="220"
            style={{
              position: "absolute",
              inset: 0,
              transform: `rotate(${ringRot}deg)`,
              filter: `drop-shadow(0 0 40px ${theme.colors.accent2}88)`,
              opacity: 0.4,
            }}
          >
            <ellipse
              cx="400"
              cy="110"
              rx="380"
              ry="90"
              fill="none"
              stroke={theme.colors.accent2}
              strokeWidth="2"
              strokeDasharray="6 14"
            />
          </svg>
          <div
            style={{
              position: "relative",
              fontFamily: theme.fonts.heading,
              fontWeight: 900,
              fontSize: 130,
              letterSpacing: -4,
              lineHeight: 1,
              background: `linear-gradient(120deg, ${theme.colors.accent2}, #fff, ${theme.colors.accent3})`,
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              padding: "20px 60px",
            }}
          >
            {t.brand}
          </div>
        </div>

        <div
          style={{
            opacity: subP * 0.9,
            transform: `translateY(${interpolate(subP, [0, 1], [20, 0])}px)`,
            fontFamily: theme.fonts.heading,
            fontWeight: 500,
            fontSize: 32,
            color: theme.colors.text,
            maxWidth: 1200,
            lineHeight: 1.35,
          }}
        >
          {t.sub}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
