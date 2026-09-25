# simplicio-fast

[English](../README.md) · **简体中文**

面向软件智能体的二进制、增量式、内存映射语义上下文。

普通源文件生成派生缓存 `.sfast`，并通过 `mmap` 读取。未修改的文件通过 SHA-256
复用，源代码始终是唯一事实来源。

在包含 500 个文件和 1,500 个符号的 POC 中，查询速度约提升 23 倍，查询 CPU
降低 95.65%。这是特定环境中的实测结果，并非通用保证。

```bash
git clone https://github.com/wesleysimplicio/simplicio-fast
cd simplicio-fast && python -m pip install -e .
simplicio-fast build .
simplicio-fast doctor
simplicio-fast context UserService --root .
```

在正式智能体流程中，`simplicio-mapper` 是强制依赖，并负责生成规范 ContextGraph。
请参阅 [AGENTS.md](../AGENTS.md) 和[完整 README](../README.md)。
