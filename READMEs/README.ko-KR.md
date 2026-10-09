# 🔁 simplicio-loop

<p align="center">
  <a href="../docs/REPOSITORY_GOVERNANCE.md"><img src="https://img.shields.io/badge/CI-local%20gate%20is%20authoritative-888888" alt="Validation status: the local scripts/check.py gate is authoritative; GitHub Actions is not required evidence"></a>
  <a href="https://github.com/simpletibr/simplicio-loop/stargazers"><img src="https://img.shields.io/github/stars/simpletibr/simplicio-loop?style=social" alt="Stars"></a>
  <a href="../docs/EXTENSION_POINTS_SERVICE.md"><img src="https://img.shields.io/badge/extension%20points-50-00E08A" alt="50 extension points"></a>
  <a href="../LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
  <a href="https://discord.gg/wM6tr7xVb"><img src="https://img.shields.io/badge/Discord-Join%20Simplicio-5865F2?logo=discord&logoColor=white" alt="Join the Simplicio Discord"></a>
</p>

<p align="center">
  <a href="../README.md">🇬🇧 English</a> |
  <a href="README.pt-BR.md">🇧🇷 Português</a> |
  <a href="README.es-ES.md">🇪🇸 Español</a> |
  <a href="README.fr-FR.md">🇫🇷 Français</a> |
  <a href="README.de-DE.md">🇩🇪 Deutsch</a> |
  <a href="README.it-IT.md">🇮🇹 Italiano</a> |
  <a href="README.ja-JP.md">🇯🇵 日本語</a> |
  <a href="README.ko-KR.md">🇰🇷 한국어</a> |
  <a href="README.zh-CN.md">🇨🇳 简体中文</a> |
  <a href="README.ru-RU.md">🇷🇺 Русский</a> |
  <a href="README.pl-PL.md">🇵🇱 Polski</a> |
  <a href="README.tr-TR.md">🇹🇷 Türkçe</a> |
  <a href="README.nl-NL.md">🇳🇱 Nederlands</a> |
  <a href="README.hi-IN.md">🇮🇳 हिन्दी</a> |
  <a href="README.ar-SA.md">🇸🇦 العربية</a>
</p>

**simplicio-loop는 GitHub 이슈를 테스트된 PR로 바꿉니다. 저장소를 매핑하고, AI가 계획하고, 결정적 편집기가 적용하고, 테스트가 검증하고, 스팩이 리뷰합니다.**

<p align="center">
  <img src="../docs/assets/readme/how-it-works.gif" alt="8단계 애니메이션 흐름: 이슈, 인테이크, 총괄 코디네이터, 스팩, 워커(매퍼, 계획, dev-cli), 스팩 리뷰, 머지 트레인, main, Simplicio Live 칸반" width="920" />
</p>

## 기능

세 가지 오퍼레이터: `simplicio-mapper`(맵), 플래너 모델(계획), `simplicio-dev-cli`(결정적 적용).

- **먼저 매핑합니다:** `simplicio-mapper`가 저장소(파일, 심볼, 테스트)를 프로젝트 맵으로 만들고, 플래너는 필요한 부분만 받습니다.
- **계획만 하고 쓰지 않습니다:** AI(claude, codex, grok, gemini 같은 exec CLI)가 샌드박스 안에서 각 변경을 계획하고, 파일을 편집하는 것은 결정적인 `dev-cli`뿐입니다.
- **PR을 열기 전에 증명합니다:** `turbo --apply - --verify`가 테스트를 실행하고, push 전에 시크릿 스캔이 돕니다.
- **스팩이 리뷰하고 묶어서 머지합니다**(진행 중: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504), [#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)). 현재 watcher는 열린 PR에서 멈춥니다.

## 설치

Python 3.11+, `git`, 그리고 GitHub 이슈용으로 인증된 `gh`가 필요합니다.

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop doctor             # check the installed stack
```

## 사용법

**Claude Code 또는 VS Code에서:**

```text
/simplicio-loop finish all the open issues
```

**24/7 watcher로**(`simpletibr/simplicio-*` 저장소를 감시하고 PR을 열는 서비스):

```bash
simplicio-loop watch247 --once --dry-run          # one simulated tick, changes nothing
simplicio-loop watch247 login-check               # are the exec CLIs logged in?
# from a repo checkout, as root, after creating the non-root user simplicio-loop:
sudo cp packaging/systemd/simplicio-loop-247.service /etc/systemd/system/
sudo cp packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env   # edit it, then chmod 600
sudo systemctl enable --now simplicio-loop-247
```

- **저장소별 opt-in:** `.simplicio/loop.toml`을 추가하고 `enabled = true`를 설정합니다.
- **이슈별 opt-in:** 신루할 수 있는 작성자(owner, member, collaborator)가 단 `loop:auto` 라벨.
- **자동 머지는 꺼져 있습니다.** watcher는 PR만 엽니다. `SIMPLICIO_247_AUTO_MERGE=1`은 진행 중입니다([#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)).

자세한 내용: [docs/WATCHER_247.md](../docs/WATCHER_247.md).

## 동작 방식

**워커 루프**(현재 `main`에서 동작): `simplicio-mapper`가 저장소를 매핑 → 플래너(exec CLI, 샌드박스 안)가 맵의 일부를 받아 계획을 작성 → `simplicio-dev-cli`가 적용(`turbo --apply - --verify`) → 테스트로 검증(두 번 실패하면 모델 역할 상향) → 시크릿 스캔 → PR. 스팩 리뷰와 머지 트레인은 진행 중입니다([#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)).

<p align="center">
  <img src="../docs/assets/readme/worker-loop.gif" alt="워커 루프: 매퍼가 저장소 매핑, 샌드박스에서 계획, 적용과 검증, 한 번의 실패, 다음 모델 역할로 상향, 시크릿 스캔, PR, 스팩 리뷰" width="920" />
</p>

**머지 트레인**(진행 중: [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)): 승인된 PR을 묶어서 한 번만 테스트하고, 빨간불이면 이분 탐색으로 문제의 PR을 찾아 나머지를 머지합니다.

<p align="center">
  <img src="../docs/assets/readme/merge-train.gif" alt="머지 트레인: PR 4개를 한 번 테스트, 빨간불, 이분 탐색으로 C 분리, 이후 A, B, D 머지" width="920" />
</p>

**스팩**(진행 중: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)): 총괄 코디네이터 1명, 스팩마다 코디네이터 1명, 각 스팩당 최대 4명의 워커. 이유: [코디네이터 1명 대 스팩](../docs/assets/readme/agents-before-after-cartoon.webp).

<p align="center">
  <img src="../docs/assets/readme/squads-cartoon.webp" alt="스팩 조직도: 총괄 코디네이터, 스팩별 코디네이터, 각 최대 4명의 워커" width="920" />
</p>

<p align="center">
  <img src="../docs/assets/readme/overview-cartoon.webp" alt="전체 흐름: 이슈, 인테이크, 총괄 코디네이터, 스팩, 샌드박스 워커, dev-cli, 스팩 승인, 머지 트레인, main, Simplicio Live 칸반" width="920" />
</p>

## 50개의 확장 포인트

24/7 서비스 경로는 50개 중 11개를 연결합니다(24개는 부분, 15개는 없음): [docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md). 나머지를 연결하는 계획은 [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509)입니다.

## 더 알아보기

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **나머지 모든 것: [docs/GUIDE.md](../docs/GUIDE.md)**(skills, runtimes, 루프, 토큰 절약, 보안, 테스트, 영어)
