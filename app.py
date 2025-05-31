from flask import Flask, render_template, request, Response
import yt_dlp
import threading
import queue

app = Flask(__name__)

progress_queues = {}

def download_video(url, user_id):
    q = progress_queues[user_id]

    def progress_hook(d):
        if d['status'] == 'downloading':
            # Sometimes progress_percent might be missing
            percent = d.get('progress_percent')
            if percent is None:
                # Fallback: calculate manually if possible
                downloaded_bytes = d.get('downloaded_bytes', 0)
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
                if total_bytes:
                    percent = downloaded_bytes / total_bytes * 100
                else:
                    percent = 0
            q.put(f"data: {percent:.2f}\n\n")  # Always send 2 decimals
        elif d['status'] == 'finished':
            q.put("data: 100.00\n\n")
            q.put("event: done\ndata: Download complete\n\n")


    ydl_opts = {
        'format': 'bestvideo[height<=2160]+bestaudio/best',
        'merge_output_format': 'mp4',
        'outtmpl': "%(title)s.%(ext)s",
        'progress_hooks': [progress_hook],
        'quiet': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download():
    url = request.form.get('url')
    user_id = request.remote_addr  # simple user ID based on IP (for demo only)
    q = queue.Queue()
    progress_queues[user_id] = q

    threading.Thread(target=download_video, args=(url, user_id), daemon=True).start()

    return Response(stream_progress(user_id), mimetype='text/event-stream')

def stream_progress(user_id):
    q = progress_queues[user_id]
    while True:
        msg = q.get()
        yield msg
        if "event: done" in msg:
            break
    progress_queues.pop(user_id, None)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
