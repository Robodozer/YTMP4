from flask import Flask, render_template, request, Response, jsonify
import yt_dlp
import os
import threading
import queue
import subprocess

app = Flask(__name__)

# Path to your exported YouTube cookies file (export using browser extension)

def get_download_path():
    import platform
    if platform.system() == 'Windows':
        import winreg
        sub_key = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders'
        downloads_guid = '{374DE290-123F-4565-9164-39C4925E467B}'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
            location = winreg.QueryValueEx(key, downloads_guid)[0]
        return location
    else:
        return os.path.expanduser('~/Downloads')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_info', methods=['POST'])
def video_info():
    url = request.form.get('url')
    if not url:
        return jsonify({"error": "URL missing"}), 400

    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'cookiesfrombrowser': ['chrome']
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    formats = []
    for f in info.get('formats', []):
        if not f.get('url'):
            continue
        if f.get('ext') == 'm4a':  # skip m4a formats
            continue
        formats.append({
            'format_id': f['format_id'],
            'ext': f['ext'],
            'format_note': f.get('format_note', ''),
            'height': f.get('height'),
            'tbr': f.get('tbr'),
            'fps': f.get('fps'),
            'filesize': f.get('filesize'),
            'abr': f.get('abr'),
            'vcodec': f.get('vcodec'),
            'acodec': f.get('acodec'),
            'quality_label': f.get('quality_label', ''),
            'format': f.get('format', '')
        })

    return jsonify({
        "title": info.get('title'),
        "thumbnail": info.get('thumbnail'),
        "formats": formats
    })

def download_video(url, format_id, q):
    def progress_hook(d):
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 1
            percent = downloaded / total * 100
            q.put(f"data: Downloading {percent:.2f}%\n\n")
        elif d['status'] == 'finished':
            q.put("data: Download complete\n\n")
            q.put("event: download_done\ndata: Download finished\n\n")

    downloads_path = get_download_path()
    ydl_opts = {
        'format': format_id,
        'outtmpl': os.path.join(downloads_path, '%(title)s.%(ext)s').replace('\\', '/'),
        'progress_hooks': [progress_hook],
        'quiet': True,
        'nopart': True,
        'cookiesfrombrowser': ['chrome']
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    return filename  # Return full path of downloaded file

def convert_audio(input_file, target_ext, q):
    output_file = os.path.splitext(input_file)[0] + '.' + target_ext

    cmd = ['ffmpeg', '-y', '-i', input_file]

    if target_ext == 'mp3':
        cmd += ['-vn', '-codec:a', 'libmp3lame', '-qscale:a', '2']
    elif target_ext in ('m4a', 'aac'):
        cmd += ['-vn', '-c:a', 'aac', '-b:a', '192k']
    else:
        cmd += ['-vn', '-acodec', 'copy']  # fallback: just copy audio stream

    cmd.append(output_file)

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # Optional: parse ffmpeg stderr for progress info here if you want
    _, stderr = process.communicate()

    if process.returncode != 0:
        q.put(f"event: error\ndata: Conversion failed: {stderr}\n\n")
        return None
    else:
        q.put(f"event: conversion_done\ndata: Conversion to {target_ext} complete\n\n")
        return output_file

@app.route('/download', methods=['POST'])
def download():
    url = request.form.get('url')
    format_id = request.form.get('format_id')
    target_ext = request.form.get('format_ext')  # e.g. mp3, m4a, wav, or None

    if not url or not format_id:
        return "Missing URL or format_id", 400

    q = queue.Queue()

    def generate():
        try:
            # Step 1: Download raw video/audio file with yt_dlp (no conversion here)
            filename = download_video(url, format_id, q)
            q.put(f"data: Download saved as {filename}\n\n")

            # Step 2: If target_ext specified and different from downloaded ext, convert
            downloaded_ext = os.path.splitext(filename)[1][1:].lower()
            if target_ext and target_ext.lower() != downloaded_ext:
                converted = convert_audio(filename, target_ext.lower(), q)
                if converted:
                    q.put(f"data: Converted file saved as {converted}\n\n")
                else:
                    q.put(f"event: error\ndata: Conversion failed\n\n")
            else:
                q.put(f"data: No conversion needed\n\n")

            q.put("event: done\ndata: All done\n\n")

        except Exception as e:
            q.put(f"event: error\ndata: {str(e)}\n\n")

    threading.Thread(target=generate).start()

    return Response(iter(q.get, None), mimetype='text/event-stream')


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
