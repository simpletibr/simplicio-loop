import React, { createContext, useContext } from "react";
import { Lang, STRINGS_WHY } from "./i18n";

const WhyLangContext = createContext<Lang>("pt");

export const WhyLangProvider: React.FC<{
  lang: Lang;
  children: React.ReactNode;
}> = ({ lang, children }) => (
  <WhyLangContext.Provider value={lang}>{children}</WhyLangContext.Provider>
);

export const useWhyLang = (): Lang => useContext(WhyLangContext);

export const useWhyT = () => STRINGS_WHY[useContext(WhyLangContext)];
