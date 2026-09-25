import React from "react";
import { Composition } from "remotion";
import { SkillsTutorial, TOTAL_DURATION } from "./SkillsTutorial";
import {
  WhyLlmProjectMapper,
  WHY_TOTAL_DURATION,
} from "./why/WhyLlmProjectMapper";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="SkillsTutorialPT"
        component={SkillsTutorial}
        durationInFrames={TOTAL_DURATION}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{ language: "pt" as const }}
      />
      <Composition
        id="SkillsTutorialEN"
        component={SkillsTutorial}
        durationInFrames={TOTAL_DURATION}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{ language: "en" as const }}
      />
      <Composition
        id="WhyLlmProjectMapperPT"
        component={WhyLlmProjectMapper}
        durationInFrames={WHY_TOTAL_DURATION}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{ language: "pt" as const }}
      />
      <Composition
        id="WhyLlmProjectMapperEN"
        component={WhyLlmProjectMapper}
        durationInFrames={WHY_TOTAL_DURATION}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{ language: "en" as const }}
      />
    </>
  );
};
