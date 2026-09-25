#!/usr/bin/env node

import {serializeSrt} from "@remotion/captions";
import {spawnSync} from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import narration from "../src/why/narration.json" with {type: "json"};

const ROOT = path.resolve(import.meta.dirname, "..");
const FPS = 30;

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    encoding: "utf8",
    stdio: "pipe",
    ...options,
  });

  if (result.status !== 0) {
    throw new Error(
      `${command} ${args.join(" ")} failed with exit code ${result.status}\n` +
      `${result.stderr || result.stdout || ""}`,
    );
  }

  return result;
}

function ensureCommand(name) {
  const check = spawnSync("sh", ["-lc", `command -v ${name}`], {
    cwd: ROOT,
    encoding: "utf8",
  });
  if (check.status !== 0) {
    throw new Error(`Required command not found in PATH: ${name}`);
  }
}

function selectLanguages(argv) {
  const requested = argv.filter((arg) => arg === "pt" || arg === "en");
  return requested.length > 0 ? requested : ["pt", "en"];
}

function totalDurationSeconds() {
  const lastCue = narration.timeline[narration.timeline.length - 1];
  return (lastCue.fromFrame + lastCue.durationInFrames) / FPS;
}

function voiceFor(lang) {
  const track = narration.tracks[lang];
  const envKey = lang === "pt" ? "WHY_PT_VOICE" : "WHY_EN_VOICE";
  return process.env[envKey] || track.voice;
}

function buildCaptions(lang) {
  const track = narration.tracks[lang];
  return narration.timeline.map((cue, index) => ({
    text: track.cues[index],
    startMs: Math.round((cue.fromFrame / FPS) * 1000),
    endMs: Math.round(((cue.fromFrame + cue.durationInFrames) / FPS) * 1000),
    timestampMs: null,
    confidence: null,
  }));
}

function cueAudioPath(tmpDir, cueId) {
  return path.join(tmpDir, `${cueId}.aiff`);
}

function renderCueFiles(lang, tmpDir) {
  const track = narration.tracks[lang];
  const voice = voiceFor(lang);

  return narration.timeline.map((cue, index) => {
    const text = track.cues[index];
    const cuePath = cueAudioPath(tmpDir, cue.id);
    const textPath = path.join(tmpDir, `${cue.id}.txt`);
    fs.writeFileSync(textPath, `${text}\n`);

    run("say", [
      "-v", voice,
      "-r", String(track.rate),
      "-o", cuePath,
      "-f", textPath,
    ]);

    return {
      ...cue,
      text,
      cuePath,
    };
  });
}

function buildTrack(lang, cues) {
  const outputRel = narration.tracks[lang].output;
  const outputAbs = path.join(ROOT, "public", outputRel);
  fs.mkdirSync(path.dirname(outputAbs), {recursive: true});

  const args = [
    "-y",
    "-f", "lavfi",
    "-t", totalDurationSeconds().toFixed(3),
    "-i", "anullsrc=r=48000:cl=stereo",
  ];

  const filterParts = [];
  const mixInputs = ["[0:a]"];

  for (const [index, cue] of cues.entries()) {
    args.push("-i", cue.cuePath);
    const delayMs = Math.round((cue.fromFrame / FPS) * 1000);
    const label = `a${index + 1}`;
    filterParts.push(
      `[${index + 1}:a]adelay=${delayMs}|${delayMs},volume=1[${label}]`,
    );
    mixInputs.push(`[${label}]`);
  }

  filterParts.push(
    `${mixInputs.join("")}amix=inputs=${mixInputs.length}:duration=longest:normalize=0[mix]`,
  );

  args.push(
    "-filter_complex", filterParts.join(";"),
    "-map", "[mix]",
    "-ar", "48000",
    "-ac", "2",
    "-c:a", "aac",
    "-b:a", "192k",
    outputAbs,
  );

  run("ffmpeg", args);
  return {outputRel};
}

function writeCaptions(lang) {
  const outputAbs = path.join(ROOT, "public", "captions", `why-${lang}.srt`);
  fs.mkdirSync(path.dirname(outputAbs), {recursive: true});
  const srt = serializeSrt({
    lines: buildCaptions(lang).map((caption) => [caption]),
  });
  fs.writeFileSync(outputAbs, srt);
  return path.relative(path.join(ROOT, "public"), outputAbs);
}

function main() {
  ensureCommand("say");
  ensureCommand("ffmpeg");

  const languages = selectLanguages(process.argv.slice(2));
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "lpm-why-voice-"));

  try {
    for (const lang of languages) {
      const cues = renderCueFiles(lang, tmpDir);
      const {outputRel} = buildTrack(lang, cues);
      const captionsRel = writeCaptions(lang);
      process.stdout.write(`generated ${outputRel}\n`);
      process.stdout.write(`generated ${captionsRel}\n`);
    }
  } finally {
    fs.rmSync(tmpDir, {recursive: true, force: true});
  }
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
}
