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

export const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useT().outro;

  const titleP = spring({ frame: frame - 6, fps, config: { damping: 15, stiffness: 100 } });
  const recapP = spring({ frame: frame - 24, fps, config: { damping: 15, stiffness: 100 } });
  const ctaP = spring({ frame: frame - 60, fps, config: { damping: 14, stiffness: 100 } });

  return (
    <AbsoluteFill>
      <BackgroundFX variant="purple" />
      <AbsoluteFill
        style={{
          alignItems: "center",
          justifyContent: "center",
          padding: 80,
          gap: 32,
        }}
      >
        <div
          style={{
            fontFamily: theme.fonts.heading,
            fontSize: 100,
            fontWeight: 900,
            background: `linear-gradient(120deg, ${theme.colors.text}, ${theme.colors.accent2}, ${theme.colors.accent3})`,
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            opacity: titleP,
            transform: `translateY(${interpolate(titleP, [0, 1], [40, 0])}px)`,
            textAlign: "center",
            lineHeight: 1.05,
            letterSpacing: -3,
          }}
        >
          {t.title}
        </div>

        <div
          style={{
            fontFamily: theme.fonts.heading,
            fontSize: 32,
            color: theme.colors.textMuted,
            opacity: recapP,
            transform: `translateY(${interpolate(recapP, [0, 1], [25, 0])}px)`,
            textAlign: "center",
            maxWidth: 1100,
            lineHeight: 1.4,
          }}
        >
          {t.subtitlePre}
          <b style={{ color: theme.colors.text }}>{t.subtitleMid}</b>
          {t.subtitlePost}
        </div>

        {/* Recap pills */}
        <div
          style={{
            display: "flex",
            gap: 18,
            flexWrap: "wrap",
            justifyContent: "center",
            maxWidth: 1200,
          }}
        >
          {[
            { label: t.pills[0], icon: "🎭", color: theme.colors.accent2 },
            { label: t.pills[1], icon: "📝", color: theme.colors.accent3 },
            { label: t.pills[2], icon: "📋", color: theme.colors.yellow },
            { label: t.pills[3], icon: "✅", color: theme.colors.green },
            { label: t.pills[4], icon: "🎯", color: theme.colors.accent },
          ].map((p, i) => {
            const sp = spring({
              frame: frame - 38 - i * 4,
              fps,
              config: { damping: 16, stiffness: 130 },
            });
            return (
              <div
                key={p.label}
                style={{
                  padding: "12px 20px",
                  borderRadius: 999,
                  background: `${p.color}22`,
                  border: `1px solid ${p.color}66`,
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  opacity: sp,
                  transform: `scale(${interpolate(sp, [0, 1], [0.8, 1])})`,
                }}
              >
                <span style={{ fontSize: 22 }}>{p.icon}</span>
                <span
                  style={{
                    fontFamily: theme.fonts.mono,
                    fontSize: 18,
                    fontWeight: 600,
                    color: theme.colors.text,
                  }}
                >
                  {p.label}
                </span>
              </div>
            );
          })}
        </div>

        {/* CTA */}
        <div
          style={{
            opacity: ctaP,
            transform: `translateY(${interpolate(ctaP, [0, 1], [30, 0])}px)`,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 14,
            marginTop: 30,
          }}
        >
          <div
            style={{
              fontFamily: theme.fonts.mono,
              fontSize: 22,
              color: theme.colors.accent2,
              padding: "14px 28px",
              borderRadius: 999,
              background: "rgba(124, 92, 255, 0.15)",
              border: `1px solid ${theme.colors.accent}88`,
            }}
          >
            {t.ctaCommand}
          </div>
          <div
            style={{
              fontFamily: theme.fonts.heading,
              fontSize: 22,
              color: theme.colors.textMuted,
            }}
          >
            {t.ctaLine}
          </div>
        </div>

        <div
          style={{
            position: "absolute",
            bottom: 40,
            fontFamily: theme.fonts.mono,
            fontSize: 16,
            color: theme.colors.textMuted,
            letterSpacing: 2,
            opacity: ctaP,
          }}
        >
          {t.footer}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
