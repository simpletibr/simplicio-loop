import React from "react";
import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
} from "remotion";

type Props = {
  durationInFrames: number;
  fadeFrames?: number;
  children: React.ReactNode;
};

export const SceneTransition: React.FC<Props> = ({
  durationInFrames,
  fadeFrames = 14,
  children,
}) => {
  const frame = useCurrentFrame();

  const inOpacity = interpolate(frame, [0, fadeFrames], [0, 1], {
    extrapolateRight: "clamp",
  });
  const outOpacity = interpolate(
    frame,
    [durationInFrames - fadeFrames, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp" },
  );
  const opacity = Math.min(inOpacity, outOpacity);

  const scaleIn = interpolate(frame, [0, fadeFrames], [1.05, 1], {
    extrapolateRight: "clamp",
  });
  const scaleOut = interpolate(
    frame,
    [durationInFrames - fadeFrames, durationInFrames],
    [1, 0.97],
    { extrapolateLeft: "clamp" },
  );
  const scale = Math.min(scaleIn, scaleOut);

  return (
    <AbsoluteFill style={{ opacity, transform: `scale(${scale})` }}>
      {children}
    </AbsoluteFill>
  );
};
