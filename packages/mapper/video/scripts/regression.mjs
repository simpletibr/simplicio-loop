#!/usr/bin/env node
// Regression test: bundle once, render 9 stills per language (PT + EN)
// at the scene's settled frame. Fails (exit 1) if any PNG is below 30 KB.

import { bundle } from "@remotion/bundler";
import { selectComposition, renderStill } from "@remotion/renderer";
import path from "node:path";
import fs from "node:fs";
import { performance } from "node:perf_hooks";

const ROOT = path.resolve(import.meta.dirname, "..");
const ENTRY = path.join(ROOT, "src", "index.ts");

const FRAMES = [
  { id: "01-intro", frame: 130 },
  { id: "02-what-are-skills", frame: 310 },
  { id: "03-catalog", frame: 490 },
  { id: "04-playwright", frame: 730 },
  { id: "05-commits", frame: 970 },
  { id: "06-how-to-invoke", frame: 1180 },
  { id: "07-create-your-own", frame: 1390 },
  { id: "08-best-practices", frame: 1570 },
  { id: "09-outro", frame: 1750 },
];

const LANGS = [
  { lang: "pt", composition: "SkillsTutorialPT", outDir: path.join(ROOT, "evidence") },
  { lang: "en", composition: "SkillsTutorialEN", outDir: path.join(ROOT, "evidence-en") },
];

const main = async () => {
  for (const l of LANGS) {
    fs.mkdirSync(l.outDir, { recursive: true });
  }

  const tBundle = performance.now();
  console.log("Bundling…");
  const serveUrl = await bundle({
    entryPoint: ENTRY,
    onProgress: () => {},
    webpackOverride: (c) => c,
  });
  console.log(`  bundle ok in ${((performance.now() - tBundle) / 1000).toFixed(1)}s`);

  const allFailed = [];
  for (const l of LANGS) {
    console.log(`\n=== ${l.lang.toUpperCase()} (${l.composition}) ===`);
    const composition = await selectComposition({
      serveUrl,
      id: l.composition,
    });

    for (const f of FRAMES) {
      const outFile = path.join(l.outDir, `${f.id}-frame-${f.frame}.png`);
      const t0 = performance.now();
      await renderStill({
        composition,
        serveUrl,
        output: outFile,
        frame: f.frame,
        imageFormat: "png",
      });
      const dt = ((performance.now() - t0) / 1000).toFixed(1);
      const stat = fs.statSync(outFile);
      const sizeKB = (stat.size / 1024).toFixed(0);
      const ok = stat.size > 30_000;
      const mark = ok ? "OK" : "TINY";
      console.log(
        `[${mark}] ${l.lang} ${f.id.padEnd(22)} frame=${String(f.frame).padStart(4)} ` +
          `${sizeKB.padStart(5)} KB  (${dt}s)  -> ${path.relative(ROOT, outFile)}`,
      );
      if (!ok) allFailed.push(`${l.lang}:${f.id}`);
    }
  }

  console.log("");
  console.log(
    `Total: ${FRAMES.length * LANGS.length} stills · failed: ${allFailed.length}`,
  );
  if (allFailed.length > 0) {
    console.log("FAILED:", allFailed.join(", "));
    process.exit(1);
  }
  console.log("All stills rendered with reasonable size. Visual review still required.");
};

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
