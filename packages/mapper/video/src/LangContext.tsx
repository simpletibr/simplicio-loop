import React, { createContext, useContext } from "react";
import { Lang, STRINGS } from "./i18n";

const LangContext = createContext<Lang>("pt");

export const LangProvider: React.FC<{
  lang: Lang;
  children: React.ReactNode;
}> = ({ lang, children }) => (
  <LangContext.Provider value={lang}>{children}</LangContext.Provider>
);

export const useLang = (): Lang => useContext(LangContext);

export const useT = () => STRINGS[useContext(LangContext)];
