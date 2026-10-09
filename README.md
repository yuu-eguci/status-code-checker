StatusCodeChecker
===

好きなだけ URL 書いてください。
ステータスコードごとに整理します。
リンク切れとか、まとめて見たいときにどうぞ。

- Docker: 対応!
- Python: 3.14!
- Linter: ruff!
- Test: pytest!

## パッと実行してみたい

```bash
printf 'https://example.com/\nhttps://example.com/nothing\n' > urls.txt
docker compose run --rm app urls.txt
```

これで URL を順番に調べて、こんな感じにまとめてくれる。

```
200
  https://example.com/
404
  https://example.com/nothing
```

URL は 1 行に 1 つ。空行やコメントは無視するし、同じ URL は 1 回だけ。
リダイレクトは追わないので、3xx もそのまま出る。

並列で調べたり、件数だけ見たり、前回との差分を見たりもできるよ。
そのへんは [オプション一覧](docs/options.md) にまとめた。

## 開発

```bash
docker compose run --rm test
docker compose run --rm lint
```

テストと lint はこれで。GitHub Actions でも回してる。

![1](media/STATUSCODE.jpg)
