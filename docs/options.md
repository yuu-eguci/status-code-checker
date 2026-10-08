オプション一覧
===

```
python status_code_checker.py [--timeout 秒] [--workers 数] [--retry 回数]
                              [--expect パターン] [--only パターン] [--exclude パターン]
                              [-v] [--format {text,json,csv}] [FILE ...]
```

| オプション | 既定 | 説明 |
|---|---|---|
| `FILE ...` | 標準入力 | 1 行 1 URL のファイル。複数可。`-` は標準入力です。 |
| `--timeout 秒` | `10` | 1 URL あたりの接続・読み取りタイムアウトです。0 より大きい有限の数を指定します。 |
| `--workers 数` | `1` | 同時に調べる URL の数です。1 以上の整数を指定します。増やしても出力は入力順のままです。 |
| `--retry 回数` | `0` | `TIMEOUT` / `CONNECTION_ERROR` / `ERROR` になった URL を、応答があるまで最大その回数だけ調べ直します。0 以上の整数を指定します。4xx や 5xx は応答なので調べ直しません。`-v` などの時間は最後の試行のものです。 |
| `--expect パターン` | なし | 期待するステータスコードです。合わない URL が 1 つでもあれば、その件数を標準エラーに出して終了コード 1 になります。エラーグループは常に「合わない」扱いで、パターンにはコードのみ指定できます。出力は変わりません。 |
| `--only パターン` | なし | 指定したグループだけを表示します。 |
| `--exclude パターン` | なし | 指定したグループを表示から外します。`--only` と同時に指定すると両方が適用されます。 |
| `-v`, `--verbose` | オフ | 各 URL の行に、応答ヘッダが届くまでの時間 (ms)、Content-Type、Location を 2 つの空白区切りで添えます。分からない項目は省きます。 |
| `--format 形式` | `text` | `json` か `csv` にすると、グループ分けせず入力順に 1 URL 1 レコードで出します。`--only` / `--exclude` は効きます。`-v` は無視します (常に全項目を出します)。 |

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

## 終了コード

| コード | 意味 |
|---|---|
| `0` | すべての URL から応答があり、`--expect` があればすべて合いました (4xx や 5xx も「応答あり」です)。 |
| `1` | `TIMEOUT` / `CONNECTION_ERROR` / `INVALID_URL` / `ERROR` のグループが 1 つ以上あるか、`--expect` に合わない URL があります。 |
| `2` | 使い方の誤りです (URL なし、読めないファイル、不正なオプション値)。 |
