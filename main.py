import os
import time
from flask import Flask, request, render_template_string, send_file
import azure.cognitiveservices.speech as speechsdk
from openai import AzureOpenAI
from dotenv import load_dotenv
import base64
from io import BytesIO
import websocket
import json
import threading
import numpy as np
import pyaudio
import wave


# Load environment variables
load_dotenv()

# Azure configuration
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# Initialize clients
client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version="2025-01-01-preview",
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
)

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable caching

# HTML Template with in-memory audio playback
HTML_PAGE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Voice Assistant</title>
    <style>
        body { 
            font-family: Arial, sans-serif; 
            max-width: 600px; 
            margin: 0 auto; 
            padding: 20px; 
            background-color: #f5f5f5;
        }
        .container {
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        button { 
            background: #4285f4; 
            color: white; 
            border: none; 
            padding: 15px 30px; 
            font-size: 18px; 
            border-radius: 5px; 
            cursor: pointer; 
            margin: 20px 0; 
            width: 100%;
            transition: background 0.3s;
        }
        button:hover { background: #3367d6; }
        .status { 
            padding: 15px; 
            margin: 15px 0; 
            border-radius: 5px; 
            text-align: center;
            font-weight: bold;
        }
        .listening { background: #ffeb3b; color: #333; }
        .processing { background: #2196f3; color: white; }
        .speaking { background: #4caf50; color: white; }
        .error { background: #f44336; color: white; }
        .conversation { 
            margin: 20px 0; 
            padding: 15px; 
            border: 1px solid #eee; 
            border-radius: 5px; 
            background: #fafafa;
        }
        .user { color: #4285f4; }
        .assistant { color: #34a853; }
        audio {
            width: 100%;
            margin-top: 15px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Voice Assistant</h1>
        <button id="activateBtn">🎤 Activate Assistant</button>
        <div id="status"></div>
        <div id="conversation"></div>
    </div>
    
    <script>
        document.getElementById('activateBtn').addEventListener('click', async function() {
            document.querySelectorAll('audio').forEach(audio => audio.remove());
            
            const statusDiv = document.getElementById('status');
            const conversationDiv = document.getElementById('conversation');
            statusDiv.className = 'status listening';
            statusDiv.textContent = '🎤 Listening... Speak now!';
            
            try {
                // Step 1: Recognize speech
                const recognitionResponse = await fetch('/recognize', { method: 'POST' });
                const recognitionData = await recognitionResponse.json();
                
                if (!recognitionData.success) {
                    statusDiv.className = 'status error';
                    statusDiv.textContent = '❌ ' + recognitionData.message;
                    return;
                }
                
                const userInput = recognitionData.text;
                
                // Display user input
                conversationDiv.innerHTML += `
                    <div class="conversation">
                        <p class="user"><strong>You:</strong> ${userInput}</p>
                    </div>
                `;
                
                statusDiv.className = 'status processing';
                statusDiv.textContent = '🔄 Processing response...';
                
                // Step 2: Get AI response
                const aiResponse = await fetch('/generate-response', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: userInput })
                });
                
                const aiData = await aiResponse.json();
                
                if (!aiData.success) {
                    statusDiv.className = 'status error';
                    statusDiv.textContent = '❌ ' + aiData.message;
                    return;
                }
                
                const reply = aiData.reply;
                
                // Display assistant response
                conversationDiv.innerHTML += `
                    <div class="conversation">
                        <p class="assistant"><strong>Assistant:</strong> ${reply}</p>
                    </div>
                `;
                
                statusDiv.className = 'status processing';
                statusDiv.textContent = '🔊 Generating audio response...';
                
                // Step 3: Generate speech
                const speechResponse = await fetch('/generate-speech', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: reply })
                });
                
                const speechData = await speechResponse.json();
                
                if (!speechData.success) {
                    statusDiv.className = 'status error';
                    statusDiv.textContent = '❌ ' + speechData.message;
                    return;
                }
                
                // Create audio element with base64 data
                // Remove any existing audio elements
                //document.querySelectorAll('audio').forEach(audio => audio.remove());

                // Create and insert new audio element
                const audioElement = document.createElement('audio');
                audioElement.controls = true;
                audioElement.autoplay = true;

                const source = document.createElement('source');
                source.src = `data:audio/wav;base64,${speechData.audio}`;
                source.type = 'audio/wav';

                audioElement.appendChild(source);

                // Add audio to the latest assistant response
                conversationDiv.querySelector('.conversation:last-child').appendChild(audioElement);

                
                statusDiv.className = 'status speaking';
                statusDiv.textContent = '🔊 Assistant is speaking...';
                
                // Update status when audio finishes
                audioElement.onended = () => {
                    statusDiv.className = '';
                    statusDiv.textContent = '';
                };
                
            } catch (error) {
                statusDiv.className = 'status error';
                statusDiv.textContent = `❌ Error: ${error.message}`;
                console.error('Error:', error);
            }
        });
    </script>
</body>
</html>
'''
def start_lipsync_with_ws(wav_path):
    def on_message(ws, message):
        response = json.loads(message)
        if response.get("messageType") == "AuthenticationResponse" and response["data"].get("authenticated"):
            model_info = {
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": "getModel",
                "messageType": "CurrentModelRequest"
            }
            ws.send(json.dumps(model_info))
        elif response.get("messageType") == "CurrentModelResponse":
            threading.Thread(target=lipsync_wav, args=(ws, wav_path), daemon=True).start()

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

    ws = websocket.WebSocketApp(
        "ws://localhost:8001",
        on_open=on_open,
        on_message=on_message
    )

    threading.Thread(target=ws.run_forever, daemon=True).start()


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

@app.route("/")
def index():
    return render_template_string(HTML_PAGE)

# Speech recognition endpoint
@app.route('/recognize', methods=['POST'])
def recognize():
    """Capture and transcribe speech from microphone"""
    config = speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    config.speech_recognition_language = "en-US"
    audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)
    recognizer = speechsdk.SpeechRecognizer(speech_config=config, audio_config=audio_config)
    
    try:
        print("Listening...")
        result = recognizer.recognize_once_async().get()
        
        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            return {
                "success": True,
                "text": result.text
            }
        else:
            return {
                "success": False,
                "message": "Speech not recognized. Please try again."
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Recognition error: {str(e)}"
        }

# Conversation history
conversation_history = [{"role": "system", "content": "You are a helpful assistant."}]

# AI response generation endpoint
@app.route('/generate-response', methods=['POST'])
def generate_response():
    """Get AI response from Azure OpenAI"""
    data = request.json
    user_input = data.get('text', '')
    
    if not user_input:
        return {
            "success": False,
            "message": "No input provided"
        }
    
    try:
        conversation_history.append({"role": "user", "content": user_input})
        
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=conversation_history,
            temperature=0.7,
            max_tokens=250
        )
        
        reply = response.choices[0].message.content
        conversation_history.append({"role": "assistant", "content": reply})
        
        return {
            "success": True,
            "reply": reply
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"AI error: {str(e)}"
        }

# Text-to-speech endpoint
@app.route('/generate-speech', methods=['POST'])
def generate_speech():
    """Convert text to speech and return as base64"""
    data = request.json
    text = data.get('text', '')
    
    if not text:
        return {
            "success": False,
            "message": "No text provided"
        }
    
    try:
        # Configure speech synthesizer
        config = speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
        config.speech_synthesis_voice_name = "en-GB-SoniaNeural"
        
        # Use in-memory stream instead of file
        stream = BytesIO()
        audio_output_stream = speechsdk.audio.PushAudioOutputStream(stream)
        audio_config = speechsdk.audio.AudioOutputConfig(stream=audio_output_stream)
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=audio_config)
        
        # Synthesize speech to memory
        result = synthesizer.speak_text_async(text).get()
        
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            # Get audio data as bytes
            audio_data = result.audio_data
            temp_path = "static/generated.wav"
            with wave.open(temp_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(20000)
                wf.writeframes(audio_data)

            # Start lipsync
            start_lipsync_with_ws(temp_path)
            # Convert to base64 for web playback
            # audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            
            
            return {
                "success": True,
                # "audio": audio_base64
            }
        else:
            return { 
                "success": False,
                "message": f"Speech synthesis failed: {result.reason}"
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Speech error: {str(e)}"
        }

if __name__ == '__main__':
    app.run(port=5000, debug=True)
