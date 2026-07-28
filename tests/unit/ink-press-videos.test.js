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

    assert.ok(fs.statSync(videoPath).size > 0, 'empty video: ' + link);
    assert.ok(readmeText.includes('(' + link + ')'), 'missing README link: ' + link);
  }
});
