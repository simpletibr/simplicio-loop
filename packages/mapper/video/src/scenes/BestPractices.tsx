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

const TIP_ICONS = ["📏", "♻️", "🎯", "✍️", "✅", "💡"];

export const BestPractices: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useT().bestPractices;
  const TIPS = t.tips.map((tip, i) => ({
    icon: TIP_ICONS[i],
    title: tip.title,
    text: tip.body,
  }));

  return (
    <AbsoluteFill>
      <BackgroundFX variant="purple" />
      <AbsoluteFill style={{ padding: "80px 100px", flexDirection: "column", gap: 32 }}>
        <div>
          <div
            style={{
              fontFamily: theme.fonts.mono,
              fontSize: 22,
              color: theme.colors.green,
              letterSpacing: 4,
              marginBottom: 8,
              textTransform: "uppercase",
            }}
          >
            {t.overline}
          </div>
          <AnimatedText text={t.title} size={78} align="left" gradient />
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 22,
            flex: 1,
          }}
        >
          {TIPS.map((tip, i) => {
            const p = spring({
              frame: frame - 25 - i * 7,
              fps,
              config: { damping: 14, stiffness: 110 },
            });
            return (
              <div
                key={tip.title}
                style={{
                  padding: 28,
                  borderRadius: 22,
                  background:
                    "linear-gradient(160deg, rgba(255,255,255,0.07) 0%, rgba(255,255,255,0.02) 100%)",
                  border: "1px solid rgba(255,255,255,0.10)",
                  backdropFilter: "blur(10px)",
                  opacity: p,
                  transform: `translateY(${interpolate(p, [0, 1], [40, 0])}px) scale(${interpolate(p, [0, 1], [0.94, 1])})`,
                  boxShadow: "0 16px 40px rgba(0,0,0,0.3)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                }}
              >
                <div style={{ fontSize: 50 }}>{tip.icon}</div>
                <div
                  style={{
                    fontFamily: theme.fonts.heading,
                    fontSize: 28,
                    fontWeight: 800,
                    color: theme.colors.text,
                  }}
                >
                  {tip.title}
                </div>
                <div
                  style={{
                    fontFamily: theme.fonts.heading,
                    fontSize: 19,
                    color: theme.colors.textMuted,
                    lineHeight: 1.4,
                  }}
                >
                  {tip.text}
                </div>
              </div>
            );
          })}
        </div>

        <div
          style={{
            opacity: spring({ frame: frame - 90, fps, config: { damping: 14, stiffness: 100 } }),
            transform: `translateY(${interpolate(
              spring({ frame: frame - 90, fps, config: { damping: 14, stiffness: 100 } }),
              [0, 1],
              [30, 0],
            )}px)`,
            padding: "24px 32px",
            borderRadius: 18,
            background: `${theme.colors.red}15`,
            border: `1px solid ${theme.colors.red}55`,
            display: "flex",
            alignItems: "center",
            gap: 18,
          }}
        >
          <div style={{ fontSize: 44 }}>🚫</div>
          <div>
            <div
              style={{
                fontFamily: theme.fonts.heading,
                fontSize: 22,
                fontWeight: 700,
                color: theme.colors.red,
                marginBottom: 4,
                textTransform: "uppercase",
                letterSpacing: 2,
              }}
            >
              {t.notForLabel}
            </div>
            <div
              style={{
                fontFamily: theme.fonts.heading,
                fontSize: 22,
                color: theme.colors.text,
                lineHeight: 1.4,
              }}
            >
              {t.notForBody[0]}
              <b>{t.notForBody[1]}</b>
              {t.notForBody[2]}
              <b>{t.notForBody[3]}</b>
              {t.notForBody[4]}
              <b>{t.notForBody[5]}</b>
              {t.notForBody[6] ?? ""}
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
