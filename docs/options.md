オプション一覧
===

```
python status_code_checker.py [--timeout 秒] [--workers 数] [--retry 回数]
                              [--head] [--header '名前: 値']
                              [--expect パターン] [--only パターン] [--exclude パターン]
                              [-v] [--summary] [--format {text,json,csv}]
                              [--diff 前回.json]
                              [--version] [FILE ...]
```

`uvx --from git+https://github.com/yuu-eguci/status-code-checker status-code-checker` や、`uv sync` 後の `uv run status-code-checker` でも同じオプションで動きます。

| オプション | 既定 | 説明 |
|---|---|---|
| `--version` | - | バージョンを表示して終了します。 |
| `FILE ...` | 標準入力 | 1 行 1 URL のファイル。複数可。`-` は標準入力です。 |
| `--timeout 秒` | `10` | 1 URL あたりの接続・読み取りタイムアウトです。0 より大きい有限の数を指定します。 |
| `--workers 数` | `1` | 同時に調べる URL の数です。1 以上の整数を指定します。増やしても出力は入力順のままです。 |
| `--retry 回数` | `0` | `TIMEOUT` / `CONNECTION_ERROR` / `ERROR` になった URL を、応答があるまで最大その回数だけ調べ直します。0 以上の整数を指定します。4xx や 5xx は応答なので調べ直しません。`-v` などの時間は最後の試行のものです。 |
| `--head` | オフ | GET の代わりに HEAD を送ります。本文を持たない分サーバーの負担は軽いですが、HEAD に GET と違うコード (405 など) を返すサーバーもあるので既定は GET です。 |
| `--header '名前: 値'` | なし | すべてのリクエストに付けるヘッダです。複数回指定でき、同じ名前なら後のものが勝ちます。`User-Agent` も上書きできます。`:` がない、名前が空、ASCII 以外や改行を含むものは使い方の誤りです。ホストが違う URL にも同じヘッダを送るので、`Authorization` などの秘密を付けるときは別サイトの URL と混ぜないでください。コマンドラインの値は `ps` などで他のユーザーに見えることがあります。 |
| `--expect パターン` | なし | 期待するステータスコードです。合わない URL が 1 つでもあれば、その件数を標準エラーに出して終了コード 1 になります。エラーグループは常に「合わない」扱いで、パターンにはコードのみ指定できます。出力は変わりません。 |
| `--only パターン` | なし | 指定したグループだけを表示します。 |
| `--exclude パターン` | なし | 指定したグループを表示から外します。`--only` と同時に指定すると両方が適用されます。 |
| `-v`, `--verbose` | オフ | 各 URL の行に、応答ヘッダが届くまでの時間 (ms)、Content-Type、Location を 2 つの空白区切りで添えます。分からない項目は省きます。 |
| `--summary` | オフ | URL を並べず、グループごとの件数だけを `200: 12` の形で 1 行ずつ表示します。並びはテキスト出力と同じです。`--only` / `--exclude` は効き、`-v` は無視します。`--format json` / `csv` や `--diff` とは併用できません。終了コードは変わりません。 |
| `--diff 前回.json` | なし | `--format json` で保存した前回の結果と比べ、グループが変わった URL (`CHANGED`)、前回なかった URL (`ADDED`)、今回なかった URL (`REMOVED`) だけを表示します。変化がなければ何も表示しません。並びは入力順 (`REMOVED` は前回の JSON の順) です。`--format json` / `csv` や `--summary` とは併用できず、`--only` / `--exclude` / `-v` は無視します。前回を `--only` / `--exclude` 付きで保存していると、絞られていた URL は `ADDED` 扱いになります。終了コードは今回の結果で決まります。 |
| `--format 形式` | `text` | `json` か `csv` にすると、グループ分けせず入力順に 1 URL 1 レコードで出します。`--only` / `--exclude` は効きます。`-v` は無視します (常に全項目を出します)。`--summary` とは併用できません。 |

`-v` の出力例です。本文はダウンロードしないので、時間は応答ヘッダが届くまでの時間です (エラーの場合は諦めるまでの時間)。

```
200
  https://example.com/  38ms  text/html
301
  http://example.com/old  41ms  text/html  -> https://example.com/new
TIMEOUT
  https://example.com/slow  10002ms
```

`--only` と `--exclude` は表示だけを絞ります。終了コードは絞る前の結果で決まります。

`--summary` の出力例です。

```
200: 12
404: 2
TIMEOUT: 1
```

## パターン

カンマ区切りで複数指定できます。

| 書き方 | 意味 | 例 |
|---|---|---|
| `NNN` | そのステータスコード | `200`, `404` |
| `Nxx` | そのクラスのコード全部 | `2xx`, `3xx` |
| グループ名 | エラーグループ (`--only` / `--exclude` のみ) | `TIMEOUT`, `CONNECTION_ERROR`, `INVALID_URL`, `ERROR` |

書き方が違うパターンは使い方の誤り (終了コード 2) です。

## JSON / CSV の項目

| 項目 | 内容 |
|---|---|
| `url` | 入力した URL です。 |
| `group` | テキスト出力の見出しと同じ文字列です (`"200"`, `"TIMEOUT"` など)。 |
| `status` | ステータスコードの数値です。応答がなければ `null` です。 |
| `location` | Location ヘッダです。なければ `null` です。 |
| `content_type` | Content-Type ヘッダです。なければ `null` です。 |
| `elapsed_ms` | 応答ヘッダが届くまで (エラーなら諦めるまで) の時間 (ms) です。`--retry` 時は最後の試行の時間で、`INVALID_URL` では `null` です。 |

JSON は `{"schema": 1, "results": [...]}` の形です。`schema` は項目の形が変わったときに増やします。

```json
{
  "schema": 1,
  "results": [
    {
      "url": "https://example.com/",
      "group": "200",
      "status": 200,
      "location": null,
      "content_type": "text/html",
      "elapsed_ms": 38
    }
  ]
}
```

CSV は 1 行目が見出し (`url,group,status,location,content_type,elapsed_ms`) です。JSON で `null` の項目は CSV では空欄です。

表示する URL がなければ、JSON は `results` が空配列、CSV は見出し行だけになります。

## --diff の出力例

```bash
docker compose run --rm app --format json urls.txt > last.json
# 後日
docker compose run --rm app --diff last.json urls.txt
```

```
CHANGED
  https://example.com/old: 200 -> 404
ADDED
  https://example.com/new: 200
REMOVED
  https://example.com/gone: 301
```

前回の JSON が読めない、または `schema` が `1` でないときは使い方の誤り (終了コード 2) です。

## 終了コード

| コード | 意味 |
|---|---|
| `0` | すべての URL から応答があり、`--expect` があればすべて合いました (4xx や 5xx も「応答あり」です)。 |
| `1` | `TIMEOUT` / `CONNECTION_ERROR` / `INVALID_URL` / `ERROR` のグループが 1 つ以上あるか、`--expect` に合わない URL があります。 |
| `2` | 使い方の誤りです (URL なし、読めないファイル、不正なオプション値、併用できないオプション)。 |
