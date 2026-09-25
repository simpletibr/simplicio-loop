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

const TYPE_COLORS: Record<string, string> = {
  feat: theme.colors.green,
  fix: theme.colors.red,
  docs: "#60a5fa",
  refactor: theme.colors.accent,
  perf: theme.colors.yellow,
  test: theme.colors.accent2,
  build: "#fb923c",
  ci: "#a3e635",
  chore: theme.colors.textMuted,
  style: theme.colors.accent3,
};
const TYPE_ORDER = [
  "feat",
  "fix",
  "docs",
  "refactor",
  "perf",
  "test",
  "build",
  "ci",
  "chore",
  "style",
];

export const CommitsSkill: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useT().commits;
  const TYPES = TYPE_ORDER.map((type) => ({
    type,
    color: TYPE_COLORS[type],
    desc: t.typeDescs[type],
  }));

  return (
    <AbsoluteFill>
      <BackgroundFX variant="pink" />
      <AbsoluteFill style={{ padding: "80px 100px", flexDirection: "column", gap: 24 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <div
            style={{
              width: 92,
              height: 92,
              borderRadius: 22,
              background: `linear-gradient(135deg, ${theme.colors.accent3}, #db2777)`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 46,
              boxShadow: `0 16px 40px ${theme.colors.accent3}66`,
            }}
          >
            📝
          </div>
          <div>
            <div
              style={{
                fontFamily: theme.fonts.mono,
                fontSize: 22,
                color: theme.colors.accent3,
                letterSpacing: 3,
                textTransform: "uppercase",
              }}
            >
              {t.overline}
            </div>
            <AnimatedText text="conventional-commits" size={70} align="left" font="mono" gradient />
          </div>
        </div>

        {/* Anatomia da mensagem */}
        <div
          style={{
            background: theme.colors.code,
            border: `1px solid ${theme.colors.codeBorder}`,
            borderRadius: 18,
            padding: 28,
            opacity: spring({ frame: frame - 20, fps, config: { damping: 14, stiffness: 100 } }),
            transform: `translateY(${interpolate(
              spring({ frame: frame - 20, fps, config: { damping: 14, stiffness: 100 } }),
              [0, 1],
              [30, 0],
            )}px)`,
          }}
        >
          <div
            style={{
              fontFamily: theme.fonts.mono,
              fontSize: 32,
              color: theme.colors.text,
              lineHeight: 1.5,
              whiteSpace: "pre",
            }}
          >
            <Tagged label="type" color={theme.colors.green} delay={26}>
              feat
            </Tagged>
            <Tagged label="scope" color={theme.colors.accent2} delay={36}>
              (auth)
            </Tagged>
            <span style={{ color: theme.colors.textMuted }}>: </span>
            <Tagged label="subject" color={theme.colors.accent3} delay={46}>
              add password reset flow via email link
            </Tagged>
          </div>
        </div>

        {/* Tipos */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(5, 1fr)",
            gap: 12,
          }}
        >
          {TYPES.map((t, i) => {
            const p = spring({
              frame: frame - 60 - i * 3,
              fps,
              config: { damping: 16, stiffness: 130 },
            });
            return (
              <div
                key={t.type}
                style={{
                  padding: "14px 16px",
                  borderRadius: 12,
                  background: `${t.color}18`,
                  border: `1px solid ${t.color}55`,
                  opacity: p,
                  transform: `scale(${interpolate(p, [0, 1], [0.85, 1])})`,
                }}
              >
                <div
                  style={{
                    fontFamily: theme.fonts.mono,
                    fontSize: 22,
                    fontWeight: 700,
                    color: t.color,
                  }}
                >
                  {t.type}
                </div>
                <div
                  style={{
                    fontFamily: theme.fonts.heading,
                    fontSize: 16,
                    color: theme.colors.textMuted,
                    marginTop: 2,
                  }}
                >
                  {t.desc}
                </div>
              </div>
            );
          })}
        </div>

        {/* Breaking change box */}
        <div
          style={{
            padding: "18px 24px",
            borderRadius: 16,
            background: `${theme.colors.red}1a`,
            border: `1px solid ${theme.colors.red}66`,
            display: "flex",
            alignItems: "center",
            gap: 18,
            opacity: spring({ frame: frame - 95, fps, config: { damping: 14, stiffness: 100 } }),
            transform: `translateY(${interpolate(
              spring({ frame: frame - 95, fps, config: { damping: 14, stiffness: 100 } }),
              [0, 1],
              [30, 0],
            )}px)`,
          }}
        >
          <div style={{ fontSize: 40 }}>💥</div>
          <div style={{ flex: 1 }}>
            <div
              style={{
                fontFamily: theme.fonts.heading,
                fontSize: 22,
                fontWeight: 700,
                color: theme.colors.red,
                marginBottom: 4,
              }}
            >
              {t.breakingTitle}
            </div>
            <div
              style={{
                fontFamily: theme.fonts.mono,
                fontSize: 22,
                color: theme.colors.text,
              }}
            >
              <span style={{ color: theme.colors.green }}>feat</span>
              <span style={{ color: theme.colors.red, fontWeight: 800 }}>!</span>
              <span style={{ color: theme.colors.textMuted }}>: </span>
              rename /users endpoint to /accounts
            </div>
            <div
              style={{
                fontFamily: theme.fonts.mono,
                fontSize: 18,
                color: theme.colors.textMuted,
                marginTop: 4,
              }}
            >
              {t.breakingFooter}
              <span style={{ color: theme.colors.red }}>BREAKING CHANGE:</span>{" "}
              &lt;{t.breakingFooterImpact.replace(/[<>]/g, "")}&gt;
            </div>
          </div>
        </div>

        <div
          style={{
            fontFamily: theme.fonts.heading,
            fontSize: 22,
            color: theme.colors.textMuted,
            textAlign: "center",
            opacity: spring({ frame: frame - 110, fps, config: { damping: 16, stiffness: 110 } }),
          }}
        >
          {t.semverNote[0]}<b style={{ color: theme.colors.text }}>{t.semverNote[1]}</b>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Tagged: React.FC<{
  label: string;
  color: string;
  delay: number;
  children: React.ReactNode;
}> = ({ label, color, delay, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 14, stiffness: 110 } });
  return (
    <span
      style={{
        position: "relative",
        display: "inline-block",
        color,
        padding: "0 8px",
        background: `${color}22`,
        borderRadius: 6,
        opacity: p,
        transform: `translateY(${interpolate(p, [0, 1], [12, 0])}px)`,
      }}
    >
      <span
        style={{
          position: "absolute",
          top: -22,
          left: 8,
          fontSize: 14,
          fontFamily: theme.fonts.mono,
          color,
          opacity: 0.8,
          letterSpacing: 1,
          textTransform: "uppercase",
        }}
      >
        {label}
      </span>
      {children}
    </span>
  );
};
