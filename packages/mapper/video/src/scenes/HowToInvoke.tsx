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
import { Terminal } from "../components/Terminal";
import { useT } from "../LangContext";
import { theme } from "../theme";

export const HowToInvoke: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = useT().howToInvoke;

  return (
    <AbsoluteFill>
      <BackgroundFX variant="purple" />
      <AbsoluteFill style={{ padding: "80px 100px", flexDirection: "column", gap: 30 }}>
        <div>
          <div
            style={{
              fontFamily: theme.fonts.mono,
              fontSize: 22,
              color: theme.colors.accent,
              letterSpacing: 4,
              marginBottom: 8,
              textTransform: "uppercase",
            }}
          >
            {t.overline}
          </div>
          <AnimatedText text={t.title} size={70} align="left" gradient />
        </div>

        <div style={{ display: "flex", gap: 32, flex: 1 }}>
          {/* Modo 1 — explícito */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 18 }}>
            <ModeHeader
              num="01"
              icon="🎯"
              title={t.mode[0]}
              badge={t.modeBadge[0]}
              subtitle={t.modeSubtitle[0]}
              color={theme.colors.accent2}
              delay={20}
            />
            <Terminal
              delay={40}
              width="100%"
              title="claude code"
              charsPerFrame={2.0}
              lines={[
                { type: "prompt", text: t.explicit.prompt },
                { type: "out", text: t.explicit.load },
                { type: "ok", text: t.explicit.ok },
                { type: "out", text: t.explicit.create },
              ]}
            />
          </div>

          {/* Modo 2 — implícito */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 18 }}>
            <ModeHeader
              num="02"
              icon="🧠"
              title={t.mode[1]}
              badge={t.modeBadge[1]}
              subtitle={t.modeSubtitle[1]}
              color={theme.colors.accent3}
              delay={28}
            />
            <Terminal
              delay={48}
              width="100%"
              title="claude code"
              charsPerFrame={2.0}
              lines={[
                { type: "prompt", text: t.implicit.prompt },
                { type: "out", text: t.implicit.match },
                { type: "ok", text: t.implicit.ok },
                { type: "out", text: t.implicit.ready },
              ]}
            />
          </div>
        </div>

        <div
          style={{
            opacity: spring({ frame: frame - 100, fps, config: { damping: 14, stiffness: 100 } }),
            transform: `translateY(${interpolate(
              spring({ frame: frame - 100, fps, config: { damping: 14, stiffness: 100 } }),
              [0, 1],
              [30, 0],
            )}px)`,
            padding: "20px 28px",
            borderRadius: 16,
            background: `${theme.colors.yellow}18`,
            border: `1px solid ${theme.colors.yellow}66`,
            display: "flex",
            alignItems: "center",
            gap: 18,
          }}
        >
          <div style={{ fontSize: 40 }}>💡</div>
          <div
            style={{
              fontFamily: theme.fonts.heading,
              fontSize: 24,
              color: theme.colors.text,
              lineHeight: 1.4,
            }}
          >
            {t.hintBody[0]}
            <b style={{ color: theme.colors.yellow }}>{t.hintBody[1]}</b>
            {t.hintBody[2]}
            <i>{t.hintBody[3]}</i>
            {t.hintBody[4]}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const ModeHeader: React.FC<{
  num: string;
  icon: string;
  title: string;
  badge: string;
  subtitle: string;
  color: string;
  delay: number;
}> = ({ icon, title, badge, subtitle, color, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 14, stiffness: 100 } });
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        opacity: p,
        transform: `translateX(${interpolate(p, [0, 1], [-30, 0])}px)`,
      }}
    >
      <div
        style={{
          width: 64,
          height: 64,
          borderRadius: 16,
          background: `linear-gradient(135deg, ${color}, ${color}88)`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 30,
          boxShadow: `0 12px 30px ${color}55`,
        }}
      >
        {icon}
      </div>
      <div>
        <div
          style={{
            fontFamily: theme.fonts.mono,
            fontSize: 14,
            color,
            letterSpacing: 3,
          }}
        >
          {badge}
        </div>
        <div
          style={{
            fontFamily: theme.fonts.heading,
            fontSize: 32,
            fontWeight: 800,
            color: theme.colors.text,
          }}
        >
          {title}
        </div>
        <div
          style={{
            fontFamily: theme.fonts.heading,
            fontSize: 18,
            color: theme.colors.textMuted,
          }}
        >
          {subtitle}
        </div>
      </div>
    </div>
  );
};
