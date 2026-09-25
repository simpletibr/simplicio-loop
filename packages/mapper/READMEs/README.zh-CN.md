# simplicio-mapper

> 将代码仓库转化为有边界、可查询、值得人和 AI 智能体信赖的上下文。

[![PyPI](https://img.shields.io/pypi/v/simplicio-mapper?color=0ea5e9&label=PyPI)](https://pypi.org/project/simplicio-mapper/)

[规范 README 与全部语言](../README.md)

<p align="center">
  <a href="../video/assets/simplicio-mapper-ink-press.zh-CN.mp4"><img src="../assets/llm-project-mapper-hero.png" alt="代码仓库转化为由证据支持的有边界上下文" width="100%"></a>
  <br>
  <strong><a href="../video/assets/simplicio-mapper-ink-press.zh-CN.mp4">观看 36 秒产品影片</a></strong>
</p>

`simplicio-mapper` 将代码库转化为 `.simplicio/` 中的版本化产物：架构、符号、流程、规则、测试以及面向任务的上下文包。它是 Simplicio 生态系统的映射引擎，使仓库知识既足够精简以便检查，又足够明确以便审计。

## 快速开始

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper handoff . --goal "追踪认证流程" --token-budget 1200 --json
```

## 关键特性

- **有边界的检索：** `handoff` 和 `orient` 报告相关性、覆盖度、令牌预算、惩罚和保真度，而不是悄悄把整个仓库塞入提示词。
- **随变更更新的上下文：** `sync`、`history`、`diff` 与 `delta` 在变更和会话之间维护 ContextGraph。
- **证据契约：** 公开 schema、验证、置信度标签、行为回执和证书将测量事实与无依据的说法分开。
- **实用产物：** 项目地图、架构文档、端点与页面清单、流程、业务规则、上手调查和图查询。

```bash
simplicio-mapper ask . impact "UserService" --json
simplicio-mapper sync . --check --json
simplicio-mapper contract validate .simplicio
simplicio-mapper doctor --contracts
```

Python 包是规范的映射引擎。npm 包 [`@wesleysimplicio/llm-project-mapper`](https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper) 是互补的项目脚手架。

请参阅[文档站点](https://wesleysimplicio.github.io/simplicio-mapper/)、[契约](../contracts/)、[集成指南](../SIMPLICIO_INTEGRATION.md)及 [v0.23.1 发布版](https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.23.1)。采用 [MIT](../LICENSE) 许可证。
