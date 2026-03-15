# MP4圧縮ツール (mp4-comp)

`mp4-comp` は、MP4 動画を以下の 2 つの方法で圧縮できるツールです。

- 目標ファイルサイズで圧縮する
- 目標画質を言葉で選んで圧縮する

既存の「サイズを指定して 2 パス圧縮する」機能はそのまま残しつつ、GUI と画質プリセット指定を追加しています。

## 特徴

- **サイズ目標指定**: 目標サイズ (MB) を指定すると、従来通り 2 パスエンコードで狙ったサイズに近づけます。
- **画質プリセット指定**: `かなり高画質` / `高画質` / `標準画質` / `容量重視の画質` から、数値 kbps ではなく言葉で選べます。
- **現在の画質を表示**: 元動画を解析して、現在の画質を言葉で表示します。
- **進捗表示**: GUI では圧縮進捗をプログレスバーで表示します。
- **予約キュー**: 複数ジョブを予約し、順番に連続処理できます。
- **音声削除対応**: 音声を削除して出力するトグルを選べます。
- **GUI 対応**: ファイル選択、現在画質の確認、元ファイルサイズ表示、目安ファイルサイズ表示を画面から操作できます。

## 必要条件

1. **Python 3.x**
2. **FFmpeg**
   - `ffmpeg` と `ffprobe` が PATH に通っている必要があります。

## 使い方

### GUI で使う

Windows では PowerShell GUI を使うのが一番確実です。

```bash
powershell -ExecutionPolicy Bypass -File .\gui.ps1
```

GUI では以下を行えます。

- MP4 ファイルの選択
- 元動画の現在画質の確認
- 元ファイルサイズの確認
- 「目標ファイルサイズ」または「目標画質」の選択
- 目標画質時の目安ファイルサイズ確認
- 音声削除トグル
- 圧縮進捗の確認
- 複数ジョブの予約と連続実行
- 圧縮実行とステータス確認

補足:

- `gui.ps1` は `compress.py` の機能をそのまま呼び出す Windows Forms GUI です。
- `gui.py` も同梱していますが、Python の Tcl/Tk 環境が整っている場合向けです。

### CLI でサイズ指定圧縮する

従来の使い方はそのまま残しています。

```bash
python compress.py "C:\path\to\video.mp4" 100
```

第 2 引数を省略すると、デフォルトの `200MB` を使います。

```bash
python compress.py "C:\path\to\video.mp4"
```

### CLI で画質指定圧縮する

使える画質プリセット一覧:

```bash
python compress.py --list-qualities
```

画質を言葉で選んで圧縮:

```bash
python compress.py "C:\path\to\video.mp4" --mode quality --quality standard

音声を削除して出力:

```bash
python compress.py "C:\path\to\video.mp4" --mode quality --quality compact --no-audio
```

サイズ指定でも音声削除可能:

```bash
python compress.py "C:\path\to\video.mp4" 100 --no-audio
```
```

利用可能な `--quality`:

- `near_source`
- `high`
- `standard`
- `compact`

### 対話モード

引数なしで実行すると、CLI でも以下を対話的に選べます。

- 入力ファイル
- 目標ファイルサイズ
- 目標画質

```bash
python compress.py
```

## 出力

- サイズ指定圧縮: 元ファイル名に `_compressed` を付けて保存
- 画質指定圧縮: 元ファイル名に `_quality_<preset>` を付けて保存
- 音声削除時: 末尾に `_noaudio` を付けて保存

例:

- `video.mp4` -> `video_compressed.mp4`
- `video.mp4` -> `video_quality_standard.mp4`
- `video.mp4` -> `video_quality_compact_noaudio.mp4`

## 仕様メモ

- サイズ指定モード:
  - H.264 (`libx264`)
  - AAC 128kbps
  - 2 パスエンコード
- 画質指定モード:
  - H.264 (`libx264`)
  - AAC 128kbps
  - CRF ベース
  - プリセットによっては解像度を自動で抑えます

## 注意事項

- 非常に長い動画を小さいサイズに収めると、画質は大きく落ちます。
- 元動画の画質判定は、解像度と映像ビットレートをもとにした目安です。
- 画質指定モードは「見た目の方向性」を選ぶための機能であり、出力サイズを厳密には固定しません。
