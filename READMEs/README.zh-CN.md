<h1 align="center">simplicio-cli</h1>

<p align="center">
  <strong>把一行任务变成经过验证的代码变更：mapper 上下文、六层契约、diff、测试和证据。</strong><br />
  <em>命令保持英文，方便直接复制。</em>
</p>

<p align="center">
<a href="https://github.com/wesleysimplicio/simplicio-dev-cli/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/wesleysimplicio/simplicio-dev-cli?style=flat-square" /></a>
<a href="https://pypi.org/project/simplicio-cli/"><img alt="PyPI" src="https://img.shields.io/pypi/v/simplicio-cli.svg?style=flat-square" /></a>
<a href="https://pypi.org/project/simplicio-cli/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/simplicio-cli.svg?style=flat-square" /></a>
<a href="../LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-yellow?style=flat-square" /></a>
</p>

<p align="center">
<a href="../README.md">English</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.es-ES.md">Español</a> | <a href="README.ja-JP.md">日本語</a> | <a href="README.ko-KR.md">한국어</a> | <a href="README.zh-CN.md">简体中文</a> | <a href="README.it-IT.md">Italiano</a> | <a href="README.fr-FR.md">Français</a> | <a href="README.ru-RU.md">Русский</a> | <a href="README.pl-PL.md">Polski</a> | <a href="README.hi-IN.md">हिन्दी</a> | <a href="README.ar-SA.md">العربية</a> | <a href="README.he-IL.md">עברית</a> | <a href="README.ms-MY.md">Bahasa Melayu</a> | <a href="README.id-ID.md">Bahasa Indonesia</a>
</p>

<p align="center">
  <img src="../output/imagegen/simplicio-cli-readme-hero-web.png" alt="simplicio-cli preview" width="860" />
</p>

---

## 简短说明

把一行任务变成经过验证的代码变更：mapper 上下文、六层契约、diff、测试和证据。

## 快速开始

```bash
pip install -U simplicio-cli
simplicio detect "hide the Delete button for non-admins"
simplicio task "hide the Delete button for non-admins"
```

## 它做什么

- Classifies the task before execution so small fixes stay small and sprint-scale work becomes a plan.
- Loads simplicio-mapper artifacts before asking an LLM to edit.
- Keeps a verification loop around generated diffs instead of trusting the first answer.
- Works with local Simplicio1, OpenRouter, OpenAI, Anthropic, DeepSeek, Hermes, Codex and Claude-style hosts.

## 为什么这个 README 更容易获得关注

- 首屏价值清晰
- 安装前提供语言入口
- 徽章和 hero 图建立信任
- 可复制的 quick start
- 先给证据再给长说明
- 用 Star 历史展示社会证明

## 工作方式

```mermaid
flowchart LR
  mapper["simplicio-mapper
repo context"] --> current["simplicio-cli
this project"]
  prompt["simplicio-prompt
reasoning runtime"] --> current
  current --> evidence["validated evidence
tests, docs, screenshots"]
  current --> sprint["simplicio-sprint
delivery loop"]
```

## 证据与验证

- Benchmark docs compare plain prompting vs the Simplicio contract on real code tasks.
- Package metadata tests pin ecosystem dependency floors.
- The CLI is the executor layer used by SendSprint and SimplicioCode flows.

## Simplicio 生态

- [simplicio-mapper](https://github.com/wesleysimplicio/simplicio-mapper) supplies repo context before interpretation.
- [simplicio-cli](https://github.com/wesleysimplicio/simplicio-dev-cli) executes focused code tasks with verification.
- [simplicio-prompt](https://github.com/wesleysimplicio/simplicio-prompt) provides fan-out and consensus runtime patterns.
- [simplicio-sprint](https://github.com/wesleysimplicio/simplicio-sprint) turns cards into draft PR delivery loops.

## 文档标准

- [docs/PYTHON_PACKAGE_INTERDEPENDENCE.md](../docs/PYTHON_PACKAGE_INTERDEPENDENCE.md)
- [docs/LLM_USAGE_POLICY.md](../docs/LLM_USAGE_POLICY.md)
- [docs/readme-globalization-standard.md](../docs/readme-globalization-standard.md)

## Star 历史

<a href="https://www.star-history.com/#wesleysimplicio/simplicio-dev-cli&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=wesleysimplicio/simplicio-dev-cli&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=wesleysimplicio/simplicio-dev-cli&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=wesleysimplicio/simplicio-dev-cli&type=Date" />
  </picture>
</a>

## 许可证

MIT. See [LICENSE](../LICENSE).
