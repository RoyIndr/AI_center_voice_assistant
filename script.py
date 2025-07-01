import websocket
import json
import time
import threading
import numpy as np
import pyaudio
import wave

wav_path = "audio.wav"

def on_message(ws, message):
    response = json.loads(message)
    print("Received:", json.dumps(response, indent=2))
    if response.get("messageType") == "AuthenticationResponse" and response["data"].get("authenticated"):
        model_info = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "getModel",
            "messageType": "CurrentModelRequest"
        }
        ws.send(json.dumps(model_info))
    elif response.get("messageType") == "CurrentModelResponse":
        threading.Thread(target=lipsync_wav, args=(ws,wav_path), daemon=True).start()
        # threading.Thread(target=lipsync_text, args=(ws, text), daemon=True).start()

def on_open(ws):
    auth = {
        "apiName": "VTubeStudioPublicAPI",
        "apiVersion": "1.0",
        "requestID": "auth",
        "messageType": "AuthenticationRequest",
        "data": {
            "pluginName": "MyCoolPlugin",
            "pluginDeveloper": "MyName",
            "authenticationToken": "0380bfb7214af2c3a9c53101962c542d5a8528acaba4ab30a878f6112df92278"
        }
    }
    ws.send(json.dumps(auth))

def lipsync_wav(ws, wav_path):
    wf = wave.open(wav_path, 'rb')
    chunk = 1024
    # Setup audio playback
    p = pyaudio.PyAudio()
    stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    output=True)
    try:
        while True:
            data = wf.readframes(chunk)
            if not data:
                break
            # Play audio chunk
            stream.write(data)
            audio = np.frombuffer(data, dtype=np.int16)
            volume = np.linalg.norm(audio) / chunk
            mouth_value = min(volume / 500, 1.0)
            param = {
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "lipsync",
                "messageType": "InjectParameterDataRequest",
                "data": {
                    "faceFound": True,
                    "mode": "set",
                    "parameterValues": [
                        {
                            "id": "MouthOpen",
                            "value": mouth_value
                        }
                    ]
                }
            }
            ws.send(json.dumps(param))
            time.sleep(chunk / wf.getframerate())
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
        wf.close()

ws = websocket.WebSocketApp(
    "ws://localhost:8001",
    on_open=on_open,
    on_message=on_message
)
ws.run_forever()