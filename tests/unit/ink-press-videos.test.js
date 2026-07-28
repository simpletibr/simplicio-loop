'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..', '..');

const videos = [
  {
    readme: 'README.md',
    link: 'assets/video/simplicio-ink-press-en-v1.mp4',
  },
  {
    readme: 'README.pt-BR.md',
    link: 'assets/video/simplicio-ink-press-pt-br-v1.mp4',
  },
];

test('Ink Press videos are versioned assets linked from the matching READMEs', () => {
  for (const { readme, link } of videos) {
    const videoPath = path.join(ROOT, link);
    const readmeText = fs.readFileSync(path.join(ROOT, readme), 'utf8');
    const header = fs.readFileSync(videoPath).subarray(4, 12).toString('ascii');

    assert.ok(fs.statSync(videoPath).size > 5_000_000, 'unexpectedly small video: ' + link);
    assert.match(header, /^ftyp/, 'not an MP4 file: ' + link);
    assert.ok(readmeText.includes('(' + link + ')'), 'missing README link: ' + link);
  }
});

test('Ink Press generator delegates to the canonical Remotion production', () => {
  const generator = fs.readFileSync(
    path.join(ROOT, 'scripts', 'generate_ink_press_videos.sh'),
    'utf8',
  );

  assert.match(generator, /simplicio-remotion\/videos\/simplicio-dev-cli-ink-press/);
  assert.match(generator, /run validate:locales/);
  assert.match(generator, /run render:locales/);
  assert.match(generator, /run validate:renders/);
});
