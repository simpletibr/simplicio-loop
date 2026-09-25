import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { BackgroundFX } from "../components/BackgroundFX";
import { AnimatedText } from "../components/AnimatedText";
import { useT } from "../LangContext";
import { theme } from "../theme";

const SKILL_NAMES = ["playwright-e2e", "conventional-commits", "_template"] as const;
const SKILL_ICONS = ["🎭", "📝", "📋"] as const;
const SKILL_COLORS = [
  theme.colors.accent2,
  theme.colors.accent3,
  theme.colors.yellow,
];

export const Catalog: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useT().catalog;
  const footerP = spring({ frame: frame - 70, fps, config: { damping: 15, stiffness: 100 } });

  return (
    <AbsoluteFill>
      <BackgroundFX variant="dark" />
      <AbsoluteFill style={{ padding: "100px 120px", flexDirection: "column", gap: 40 }}>
        <div>
          <div
            style={{
              fontFamily: theme.fonts.mono,
              fontSize: 22,
              color: theme.colors.accent3,
              letterSpacing: 4,
              marginBottom: 8,
              textTransform: "uppercase",
            }}
          >
            {t.overline}
          </div>
          <AnimatedText text={t.title} size={84} align="left" gradient />
        </div>

        <div style={{ display: "flex", gap: 28, flex: 1, alignItems: "stretch" }}>
          {SKILL_NAMES.map((name, i) => {
            const color = SKILL_COLORS[i];
            const p = spring({
              frame: frame - 22 - i * 10,
              fps,
              config: { damping: 14, stiffness: 100 },
            });
            return (
              <div
                key={name}
                style={{
                  flex: 1,
                  padding: 32,
                  borderRadius: 24,
                  background: `linear-gradient(160deg, ${color}25 0%, rgba(255,255,255,0.02) 100%)`,
                  border: `1px solid ${color}55`,
                  backdropFilter: "blur(12px)",
                  boxShadow: `0 24px 60px ${color}33`,
                  opacity: p,
                  transform: `translateY(${interpolate(p, [0, 1], [60, 0])}px) scale(${interpolate(p, [0, 1], [0.92, 1])})`,
                  display: "flex",
                  flexDirection: "column",
                  gap: 16,
                }}
              >
                <div
                  style={{
                    width: 80,
                    height: 80,
                    borderRadius: 20,
                    background: `linear-gradient(135deg, ${color}, ${color}88)`,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 46,
                    boxShadow: `0 12px 30px ${color}66`,
                  }}
                >
                  {SKILL_ICONS[i]}
                </div>
                <div
                  style={{
                    fontFamily: theme.fonts.mono,
                    fontSize: 30,
                    fontWeight: 700,
                    color: theme.colors.text,
                  }}
                >
                  {name}
                </div>
                <div
                  style={{
                    fontFamily: theme.fonts.heading,
                    fontSize: 22,
                    color: theme.colors.textMuted,
                    lineHeight: 1.4,
                    flex: 1,
                  }}
                >
                  {t.skillDescs[i]}
                </div>
                <div
                  style={{
                    paddingTop: 16,
                    borderTop: `1px solid ${color}33`,
                    fontFamily: theme.fonts.mono,
                    fontSize: 16,
                    color,
                  }}
                >
                  .skills/{name}/SKILL.md
                </div>
              </div>
            );
          })}
        </div>

        <div
          style={{
            opacity: footerP,
            transform: `translateY(${interpolate(footerP, [0, 1], [30, 0])}px)`,
            fontFamily: theme.fonts.heading,
            fontSize: 24,
            color: theme.colors.textMuted,
            textAlign: "center",
          }}
        >
          {t.footerPrefix}
          <b style={{ color: theme.colors.text }}>{t.footerLocalLabel}</b>
          {t.footerLocalSep}
          <code style={{ color: theme.colors.accent2 }}>.skills/</code>{" · "}
          <b style={{ color: theme.colors.text }}>{t.footerGlobalLabel}</b>
          {" → "}
          <code style={{ color: theme.colors.accent2 }}>~/.claude/skills/</code>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
