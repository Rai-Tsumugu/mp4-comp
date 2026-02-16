
import os
import sys
import subprocess
import json
import math

def get_video_duration(input_file):
    """
    ffprobeを使用して動画の長さ（秒）を取得する
    """
    cmd = [
        'ffprobe',
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        '-show_streams',
        input_file
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
        # Windows環境などでcp932と判定されてエラーになるのを防ぐため、明示的にutf-8でデコード
        output_str = result.stdout.decode('utf-8', errors='ignore')
        data = json.loads(output_str)
        
        # フォーマット情報から期間を取得
        if 'format' in data and 'duration' in data['format']:
            return float(data['format']['duration'])
            
        # ストリーム情報から取得を試みる
        for stream in data.get('streams', []):
            if stream['codec_type'] == 'video':
                if 'duration' in stream:
                    return float(stream['duration'])
                    
        raise ValueError("動画の長さを取得できませんでした。")
        
    except FileNotFoundError:
        print("エラー: 'ffprobe' が見つかりません。FFmpegがインストールされ、PATHに含まれていることを確認してください。")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"エラー: ffprobeの実行に失敗しました。: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"エラー: {e}")
        sys.exit(1)

def compress_video(input_file, target_size_mb=200):
    """
    動画を指定されたサイズ（MB）以下に圧縮する
    """
    if not os.path.exists(input_file):
        print(f"エラー: ファイル '{input_file}' が見つかりません。")
        return

    # 出力ファイル名を作成
    filename, ext = os.path.splitext(input_file)
    output_file = f"{filename}_compressed{ext}"

    print(f"動画の情報を取得中: {input_file}")
    duration = get_video_duration(input_file)
    print(f"動画の長さ: {duration:.2f} 秒")

    # 目標サイズ (MB -> bits)
    # 安全マージンとして95%程度に見積もる
    target_size_bits = target_size_mb * 1024 * 1024 * 8 * 0.95
    
    # 音声ビットレート (128kbps固定)
    audio_bitrate_kbps = 128
    audio_bitrate_bits = audio_bitrate_kbps * 1000
    
    # 映像ビットレート計算
    # target_bits = (video_rate + audio_rate) * duration
    # video_rate = (target_bits / duration) - audio_rate
    
    total_bitrate = target_size_bits / duration
    video_bitrate_bits = total_bitrate - audio_bitrate_bits
    video_bitrate_kbps = video_bitrate_bits / 1000

    if video_bitrate_kbps < 100:
        print("警告: 計算されたビットレートが低すぎます（100kbps未満）。画質が著しく低下する可能性があります。")
        video_bitrate_kbps = max(video_bitrate_kbps, 50) # 最低限の制限

    print(f"目標映像ビットレート: {int(video_bitrate_kbps)}k")
    
    # 2パスエンコード
    # Windowsでは /dev/null の代わりに NUL を使用
    null_device = "NUL" if os.name == 'nt' else "/dev/null"
    
    print("エンコード中 (Pass 1/2)...")
    pass1_cmd = [
        'ffmpeg',
        '-y',
        '-i', input_file,
        '-c:v', 'libx264',
        '-b:v', f'{int(video_bitrate_kbps)}k',
        '-pass', '1',
        '-an', # 音声なし
        '-f', 'mp4',
        null_device
    ]

    try:
        subprocess.run(pass1_cmd, check=True)
    except subprocess.CalledProcessError:
        print("Pass 1 のエンコードに失敗しました。")
        return

    print("エンコード中 (Pass 2/2)...")
    pass2_cmd = [
        'ffmpeg',
        '-y',
        '-i', input_file,
        '-c:v', 'libx264',
        '-b:v', f'{int(video_bitrate_kbps)}k',
        '-pass', '2',
        '-c:a', 'aac',
        '-b:a', '128k',
        output_file
    ]

    try:
        subprocess.run(pass2_cmd, check=True)
        
        # 一時ファイルの削除 (ffmpeg2pass-0.log 等)
        for f in os.listdir('.'):
            if f.startswith('ffmpeg2pass'):
                try:
                    os.remove(f)
                except:
                    pass
                    
        print(f"圧縮完了: {output_file}")
        
        # 結果サイズの確認
        final_size = os.path.getsize(output_file) / (1024 * 1024)
        print(f"出力サイズ: {final_size:.2f} MB")
        
        if final_size > target_size_mb:
             print(f"警告: 目標サイズ ({target_size_mb}MB) を超過しました。")
        else:
             print("目標サイズ内に収まりました。")

    except subprocess.CalledProcessError:
        print("Pass 2 のエンコードに失敗しました。")


if __name__ == "__main__":
    target_size = 200
    input_path = None

    if len(sys.argv) > 1:
        input_path = sys.argv[1]
        if len(sys.argv) > 2:
            try:
                target_size = int(sys.argv[2])
            except ValueError:
                print(f"警告: 有効なターゲットサイズではありません。デフォルトの {target_size}MB を使用します。")
    else:
        print("圧縮したいMP4ファイルをドラッグ＆ドロップするか、パスを入力してください:")
        input_path = input().strip().strip('"')
        
        print(f"ターゲットサイズを入力してください（MB）[デフォルト: {target_size}]:")
        size_input = input().strip()
        if size_input:
            try:
                target_size = int(size_input)
            except ValueError:
                print(f"警告: 有効な数値ではありません。デフォルトの {target_size}MB を使用します。")

    if input_path:
        compress_video(input_path, target_size)
    else:
        print("ファイルが指定されませんでした。")
