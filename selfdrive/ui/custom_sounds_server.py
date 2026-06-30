#!/usr/bin/env python3
import os
import aiohttp
from aiohttp import web
from pathlib import Path
from openpilot.system.hardware import PC

CUSTOM_SOUNDS_DIR = Path("/data/openpilot/selfdrive/assets/sounds")
CUSTOM_SOUNDS_DIR.mkdir(parents=True, exist_ok=True)

HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
  <title>NotAutopilot Custom Sounds Portal</title>
  <style>
    body { font-family: sans-serif; max-width: 600px; margin: 40px auto; background: #222; color: #fff; }
    .card { background: #333; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
    h1 { text-align: center; }
    label { font-weight: bold; display: block; margin-bottom: 8px; }
    input[type=file] { margin-bottom: 15px; }
    button { background: #4CAF50; color: white; padding: 10px 15px; border: none; border-radius: 4px; cursor: pointer; }
    button:hover { background: #45a049; }
    .status { margin-top: 10px; font-weight: bold; }
    .success { color: #4CAF50; }
    .error { color: #f44336; }
  </style>
</head>
<body>
  <h1>Custom Sounds Portal</h1>
  <div class="card">
    <p>Upload any audio file. It will be professionally processed inside your browser (converted to Mono, 48kHz, 16-bit, Low-Pass filtered at 2500Hz, and volume adjusted) before being uploaded to the Comma!</p>
    <form id="uploadForm">
      <label for="sound_type">Select Sound to Replace:</label>
      <select id="sound_type" name="sound_type" style="margin-bottom: 15px; padding: 5px;">
        <option value="engage">Engage</option>
        <option value="disengage">Disengage</option>
        <option value="prompt">Prompt (Chime)</option>
        <option value="prompt_distracted">Prompt Distracted</option>
        <option value="refuse">Refuse</option>
        <option value="warning_soft">Warning Soft</option>
        <option value="warning_immediate">Warning Immediate</option>
      </select>
      
      <label for="file">Select audio file:</label>
      <input type="file" id="file" name="file" accept="audio/*" required>
      
      <label for="volume">Volume Multiplier: <span id="volume_val">1.0</span>x</label>
      <input type="range" id="volume" name="volume" min="0.1" max="3.0" step="0.1" value="1.0" style="margin-bottom: 20px;">
      
      <button type="submit">Process & Upload</button>
    </form>
    <div id="status" class="status"></div>
  </div>

  <script>
    function audioBufferToWav(buffer) {
      const numOfChan = buffer.numberOfChannels;
      const length = buffer.length * numOfChan * 2 + 44;
      const bufferArray = new ArrayBuffer(length);
      const view = new DataView(bufferArray);
      let offset = 0, pos = 0;

      function setUint16(data) { view.setUint16(pos, data, true); pos += 2; }
      function setUint32(data) { view.setUint32(pos, data, true); pos += 4; }

      setUint32(0x46464952); // "RIFF"
      setUint32(length - 8); // file length - 8
      setUint32(0x45564157); // "WAVE"
      setUint32(0x20746d66); // "fmt " chunk
      setUint32(16); // length = 16
      setUint16(1); // PCM
      setUint16(numOfChan);
      setUint32(buffer.sampleRate);
      setUint32(buffer.sampleRate * 2 * numOfChan); // avg. bytes/sec
      setUint16(numOfChan * 2); // block-align
      setUint16(16); // 16-bit
      setUint32(0x61746164); // "data" chunk
      setUint32(length - pos - 4); // chunk length

      const channelData = buffer.getChannelData(0);
      while (pos < length) {
        let sample = Math.max(-1, Math.min(1, channelData[offset]));
        sample = sample < 0 ? sample * 32768 : sample * 32767;
        view.setInt16(pos, sample, true);
        offset++;
        pos += 2;
      }
      return bufferArray;
    }

    document.getElementById('volume').addEventListener('input', function() {
      document.getElementById('volume_val').textContent = this.value;
    });

    document.getElementById('uploadForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const statusDiv = document.getElementById('status');
      statusDiv.textContent = 'Processing audio in browser...';
      statusDiv.className = 'status';

        const fileInput = document.getElementById('file');
      const soundType = document.getElementById('sound_type').value;
      const volumeVal = parseFloat(document.getElementById('volume').value);
      const file = fileInput.files[0];

      try {
        const arrayBuffer = await file.arrayBuffer();
        const tempContext = new (window.AudioContext || window.webkitAudioContext)();
        const audioBuffer = await tempContext.decodeAudioData(arrayBuffer);
        
        // Setup offline context strictly for Mono, 48000Hz, length of audio
        const offlineCtx = new OfflineAudioContext(1, audioBuffer.duration * 48000, 48000);
        
        const source = offlineCtx.createBufferSource();
        source.buffer = audioBuffer;

        // Apply lowpass filter at 2500Hz
        const lowpass = offlineCtx.createBiquadFilter();
        lowpass.type = 'lowpass';
        lowpass.frequency.value = 2500;

        // Apply selected volume multiplier
        const gainNode = offlineCtx.createGain();
        gainNode.gain.value = volumeVal;

        source.connect(lowpass);
        lowpass.connect(gainNode);
        gainNode.connect(offlineCtx.destination);
        source.start();

        const renderedBuffer = await offlineCtx.startRendering();
        statusDiv.textContent = 'Uploading perfectly formatted WAV...';
        
        const wavBuffer = audioBufferToWav(renderedBuffer);
        const wavBlob = new Blob([wavBuffer], { type: 'audio/wav' });

        const formData = new FormData();
        formData.append('sound_type', soundType);
        formData.append('file', wavBlob, soundType + '.wav');

        const response = await fetch('/upload', { method: 'POST', body: formData });
        const result = await response.text();
        
        if (response.ok) {
          statusDiv.textContent = result + ' (Restarting Comma software automatically!)';
          statusDiv.className = 'status success';
        } else {
          statusDiv.textContent = 'Error: ' + result;
          statusDiv.className = 'status error';
        }
      } catch (err) {
        statusDiv.textContent = 'Error: ' + err.message;
        statusDiv.className = 'status error';
      }
    });
  </script>
</body>
</html>
"""

async def handle_index(request):
    return web.Response(text=HTML_PAGE, content_type='text/html')

async def handle_upload(request):
    try:
        reader = await request.multipart()
        sound_type = None
        file_content = None

        async for field in reader:
            if field.name == 'sound_type':
                sound_type = await field.text()
            elif field.name == 'file':
                file_content = await field.read()

        if not sound_type or not file_content:
            return web.Response(text="Missing data", status=400)

        safe_sound_types = ["engage", "disengage", "prompt", "prompt_distracted", "refuse", "warning_soft", "warning_immediate", "engage_tizi", "disengage_tizi"]
        if sound_type not in safe_sound_types:
            return web.Response(text="Invalid sound type", status=400)

        final_path = CUSTOM_SOUNDS_DIR / f"{sound_type}.wav"
        with open(final_path, 'wb') as f:
            f.write(file_content)
            
        # Comma 3X uses a special hardware override for engage/disengage. We must overwrite both!
        if sound_type in ["engage", "disengage"]:
            tizi_path = CUSTOM_SOUNDS_DIR / f"{sound_type}_tizi.wav"
            with open(tizi_path, 'wb') as f:
                f.write(file_content)

        # Trigger a restart automatically but detached so it doesn't kill the HTTP response
        import subprocess
        subprocess.Popen(["sudo", "systemctl", "restart", "comma"], start_new_session=True)

        return web.Response(text=f"Success! Saved {sound_type}.wav", status=200)

    except Exception as e:
        return web.Response(text=str(e), status=500)

def main():
    app = web.Application(client_max_size=1024**2 * 50)
    app.router.add_get('/', handle_index)
    app.router.add_post('/upload', handle_upload)
    web.run_app(app, host='0.0.0.0', port=8082)

if __name__ == "__main__":
    main()
