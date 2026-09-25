# simplicio-mapper

> リポジトリを、人と AI エージェントが信頼できる、境界が明確で検索可能なコンテキストへ変換します。

[![PyPI](https://img.shields.io/pypi/v/simplicio-mapper?color=0ea5e9&label=PyPI)](https://pypi.org/project/simplicio-mapper/)

[正規 README と全言語](../README.md)

<p align="center">
  <a href="../video/assets/simplicio-mapper-ink-press.ja-JP.mp4"><img src="../assets/llm-project-mapper-hero.png" alt="リポジトリが証拠に支えられた境界付きコンテキストになる様子" width="100%"></a>
  <br>
  <strong><a href="../video/assets/simplicio-mapper-ink-press.ja-JP.mp4">36 秒の製品動画を見る</a></strong>
</p>

`simplicio-mapper` はコードベースを `.simplicio/` 配下のバージョン管理された成果物へ変換します。成果物にはアーキテクチャ、シンボル、フロー、ルール、テスト、タスク指向のコンテキストパックが含まれます。Simplicio エコシステムのマッピングエンジンとして、リポジトリ知識を検査できるほど小さく、監査できるほど明示的にします。

## クイックスタート

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper handoff . --goal "認証フローを追跡する" --token-budget 1200 --json
```

## 主な違い

- **境界付き検索：** `handoff` と `orient` は、リポジトリ全体を黙ってプロンプトへ入れる代わりに、関連性、カバレッジ、トークン予算、ペナルティ、忠実度を示します。
- **変更を追うコンテキスト：** `sync`、`history`、`diff`、`delta` が変更やセッションをまたいで ContextGraph を維持します。
- **証拠の契約：** 公開スキーマ、検証、信頼度タグ、行動レシート、証明書により、測定された事実と根拠のない主張を区別します。
- **実用的な出力：** プロジェクトマップ、アーキテクチャ文書、エンドポイントと画面の一覧、フロー、業務ルール、オンボーディング調査、グラフ問い合わせ。

```bash
simplicio-mapper ask . impact "UserService" --json
simplicio-mapper sync . --check --json
simplicio-mapper contract validate .simplicio
simplicio-mapper doctor --contracts
```

Python パッケージが正規のマッピングエンジンです。npm の [`@wesleysimplicio/llm-project-mapper`](https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper) は補完的なプロジェクトスターターです。

[ドキュメントサイト](https://wesleysimplicio.github.io/simplicio-mapper/)、[契約](../contracts/)、[統合ガイド](../SIMPLICIO_INTEGRATION.md)、[v0.23.1 リリース](https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.23.1) を参照してください。ライセンスは [MIT](../LICENSE) です。
