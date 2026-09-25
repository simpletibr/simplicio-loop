# simplicio-fast

[English](../README.md) · **日本語**

ソフトウェアエージェント向けの、バイナリ・増分・メモリマップ型セマンティックコンテキストです。

通常のソースコードから派生キャッシュ `.sfast` を構築し、`mmap` で読み取ります。変更されて
いないファイルは SHA-256 により再利用され、ソースコードは常に唯一の正となります。

500 ファイル、1,500 シンボルの POC では、クエリが約 23 倍高速で、CPU 使用量が 95.65%
減少しました。これは測定結果であり、すべての環境での保証ではありません。

```bash
git clone https://github.com/wesleysimplicio/simplicio-fast
cd simplicio-fast && python -m pip install -e .
simplicio-fast build .
simplicio-fast doctor
simplicio-fast context UserService --root .
```

正式なエージェントフローでは `simplicio-mapper` が必須で、正規 ContextGraph を生成します。
[AGENTS.md](../AGENTS.md) と [完全版 README](../README.md) を参照してください。
