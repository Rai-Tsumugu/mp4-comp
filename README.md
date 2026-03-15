# MP4圧縮ツール (mp4-comp)

`mp4-comp` は、MP4 動画を以下の 2 つの方法で圧縮できるツールです。

- 目標ファイルサイズで圧縮する
- 目標画質を言葉で選んで圧縮する

## 特徴

- **サイズ目標指定**: 目標サイズ (MB) を指定すると、2 パスエンコードで狙ったサイズに近づけます。
- **画質プリセット指定**: `かなり高画質` / `高画質` / `標準画質` / `容量重視の画質` から言葉で選べます。
- **現在の画質を表示**: 元動画を解析して、現在の画質を言葉で表示します。
- **進捗表示**: GUI では圧縮進捗をプログレスバーで表示します。
- **予約キュー**: 複数ジョブを予約し、順番に連続処理できます。
- **音声削除対応**: 音声を削除して出力するトグルを選べます。

## 必要条件

- **FFmpeg**: `ffmpeg` と `ffprobe` が PATH に通っている必要があります。
  - [FFmpeg 公式サイト](https://ffmpeg.org/download.html) からダウンロード、または `winget install ffmpeg` でインストールできます。

> `.exe` を使う場合は Python のインストールは不要です。

## 使い方

### Windows アプリ (.exe) として使う — 推奨

`dist\mp4-comp.exe` をダブルクリックするだけで起動します。Python のインストールは不要です。

初回は `build.bat` を実行して `.exe` をビルドしてください。

```
build.bat
```

ビルドが完了すると `dist\mp4-comp.exe` が生成されます。

### PowerShell GUI で使う

Python 環境がある場合は PowerShell GUI も利用できます。

```powershell
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

### CLI でサイズ指定圧縮する

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
```

音声を削除して出力:

```bash
python compress.py "C:\path\to\video.mp4" --mode quality --quality compact --no-audio
```

サイズ指定でも音声削除可能:

```bash
python compress.py "C:\path\to\video.mp4" 100 --no-audio
```

利用可能な `--quality`:

| キー | 表示名 |
|------|--------|
| `near_source` | かなり高画質 |
| `high` | 高画質 |
| `standard` | 標準画質 |
| `compact` | 容量重視の画質 |

### 対話モード

引数なしで実行すると、CLI でも対話的に設定を選べます。

```bash
python compress.py
```

## .exe のビルド方法

`build.bat` を実行すると `dist\mp4-comp.exe` が生成されます。

**前提条件:**

- Python 3.x がインストールされていること
- `pip install pyinstaller` (初回は `build.bat` が自動でインストール)

```
build.bat
```

## 出力ファイル名

| モード | 出力ファイル名 |
|--------|---------------|
| サイズ指定 | `video_compressed.mp4` |
| 画質指定 | `video_quality_standard.mp4` |
| 音声削除あり | `video_quality_compact_noaudio.mp4` |

## 仕様メモ

- **サイズ指定モード**: H.264 (`libx264`) + AAC 128kbps、2 パスエンコード
- **画質指定モード**: H.264 (`libx264`) + AAC 128kbps、CRF ベース（プリセットによって解像度を自動調整）

## 注意事項

- 非常に長い動画を小さいサイズに収めると、画質は大きく落ちます。
- 元動画の画質判定は、解像度と映像ビットレートをもとにした目安です。
- 画質指定モードは「見た目の方向性」を選ぶための機能であり、出力サイズを厳密には固定しません。
