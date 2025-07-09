import os
import time
from flask import Flask, request, render_template_string, send_file
import azure.cognitiveservices.speech as speechsdk
from openai import AzureOpenAI
from dotenv import load_dotenv
import base64
from io import BytesIO
import websocket  # <-- change back to this
import json
import threading
import numpy as np
import pyaudio
import wave
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

print(websocket.__file__)  # should show path ending in "websocket_client"
print(dir(websocket))
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

# Knowledge base for Universitas Brawijaya
UB_KNOWLEDGE_BASE = {
    "fakultas": {
        "FMIPA": "Fakultas Matematika dan Ilmu Pengetahuan Alam - memiliki jurusan Matematika, Fisika, Kimia, Biologi, dan Statistika",
        "FT": "Fakultas Teknik - memiliki jurusan Teknik Sipil, Teknik Mesin, Teknik Elektro, Teknik Pengairan, Teknik Industri, Teknik Informatika, dan Perencanaan Wilayah Kota",
        "FTP": "Fakultas Teknologi Pertanian - memiliki jurusan Teknologi Hasil Pertanian, Teknik Pertanian dan Biosistem, Teknologi Industri Pertanian, dan Teknologi Pangan dan Gizi",
        "FP": "Fakultas Pertanian - memiliki jurusan Agronomi, Proteksi Tanaman, Tanah, Sosial Ekonomi Pertanian, dan Budidaya Perairan",
        "FPet": "Fakultas Peternakan - memiliki jurusan Produksi Ternak, Nutrisi dan Makanan Ternak, Sosial Ekonomi Peternakan, dan Teknologi Hasil Ternak",
        "FK": "Fakultas Kedokteran - memiliki Program Studi Kedokteran, Kebidanan, dan Keperawatan",
        "FKG": "Fakultas Kedokteran Gigi",
        "FKIP": "Fakultas Keguruan dan Ilmu Pendidikan",
        "FISIP": "Fakultas Ilmu Sosial dan Ilmu Politik - memiliki jurusan Sosiologi, Ilmu Politik, Administrasi Publik, dan Hubungan Internasional",
        "FIA": "Fakultas Ilmu Administrasi - memiliki jurusan Administrasi Bisnis, Administrasi Publik, dan Perpustakaan",
        "FE": "Fakultas Ekonomi dan Bisnis - memiliki jurusan Ekonomi Pembangunan, Manajemen, dan Akuntansi",
        "FH": "Fakultas Hukum",
        "FIB": "Fakultas Ilmu Budaya - memiliki jurusan Sastra Indonesia, Sastra Inggris, Sastra Jepang, Sastra Cina, dan Seni Rupa",
        "FKKMK": "Fakultas Kedokteran Hewan",
        "FPIK": "Fakultas Perikanan dan Ilmu Kelautan"
    },
    "ai_center": {
        "deskripsi": "AI Center Universitas Brawijaya adalah pusat penelitian dan pengembangan kecerdasan buatan yang berfokus pada inovasi teknologi AI untuk mendukung pendidikan dan penelitian",
        "program": [
            "Pelatihan AI dan Machine Learning",
            "Workshop AI",
            "Penelitian kolaboratif"
        ],
        "fasilitas": [
            "Lab AI dengan GPU high-end",
            "Ruang kolaborasi",
            "Server komputasi cloud",
            "Perpustakaan digital AI",
            "Ruang meeting virtual reality"
        ]
    },
    "bantuan_personal": {
        "akademik": "Konseling akademik, bimbingan skripsi, tips belajar efektif",
        "mental": "Dukungan kesehatan mental, manajemen stress, motivasi",
        "karir": "Perencanaan karir, pengembangan soft skill, persiapan kerja",
        "organisasi": "Informasi organisasi kemahasiswaan, leadership training"
    }
}

# Minat dan bakat mapping
MINAT_BAKAT_MAPPING = {
    "teknologi": ["Teknik Informatika", "Teknik Elektro", "Sistem Informasi", "Teknik Industri"],
    "sains": ["Matematika", "Fisika", "Kimia", "Biologi", "Statistika"],
    "sosial": ["Sosiologi", "Ilmu Politik", "Administrasi Publik", "Hubungan Internasional"],
    "bisnis": ["Manajemen", "Akuntansi", "Ekonomi Pembangunan", "Administrasi Bisnis"],
    "kesehatan": ["Kedokteran", "Kedokteran Gigi", "Keperawatan", "Kedokteran Hewan"],
    "pendidikan": ["FKIP - berbagai jurusan keguruan"],
    "pertanian": ["Agronomi", "Proteksi Tanaman", "Teknologi Hasil Pertanian"],
    "seni": ["Seni Rupa", "Sastra Indonesia", "Sastra Inggris"],
    "hukum": ["Ilmu Hukum"],
    "komunikasi": ["Sastra", "Hubungan Internasional", "Administrasi Publik"]
}

# Enhanced conversation history with better system prompt
conversation_history = [{
    "role": "system",
    "content": f"""
Kamu adalah BRAWIJAYA AI ASSISTANT, asisten suara resmi Universitas Brawijaya yang sangat berpengetahuan dan ramah. 
Nama kamu adalah "Brava" (singkatan dari Brawijaya Assistant).

IDENTITAS DAN KEPRIBADIAN:
- Selalu perkenalkan diri sebagai "Brava, asisten AI Universitas Brawijaya"
- Gunakan bahasa Indonesia yang ramah, sopan, dan mudah dipahami
- Tunjukkan antusiasme dan kepedulian terhadap pengguna
- Berikan jawaban yang informatif namun tidak terlalu panjang (maksimal 3-4 kalimat)

KNOWLEDGE BASE UTAMA:
{json.dumps(UB_KNOWLEDGE_BASE, indent=2, ensure_ascii=False)}

MINAT BAKAT MAPPING:
{json.dumps(MINAT_BAKAT_MAPPING, indent=2, ensure_ascii=False)}

TUGAS UTAMA:
1. INFORMASI UNIVERSITAS BRAWIJAYA: Berikan informasi lengkap tentang fakultas, jurusan, fasilitas, dan program studi
2. AI CENTER UB: Jelaskan program, fasilitas, dan kegiatan AI Center
3. BANTUAN PERSONAL: Berikan dukungan untuk masalah akademik, mental, dan pengembangan diri
4. KONSULTASI JURUSAN: Bantu pengguna memilih jurusan berdasarkan minat dan bakat mereka

PANDUAN KONSULTASI JURUSAN:
- Tanyakan minat utama pengguna (teknologi, sains, sosial, bisnis, dll)
- Tanyakan mata pelajaran favorit di sekolah
- Tanyakan cita-cita atau karir yang diinginkan
- Berikan rekomendasi 2-3 jurusan yang sesuai dengan penjelasan singkat

CONTOH INTERAKSI:
User: "Halo"
Brava: "Halo! Saya Brava, asisten AI Universitas Brawijaya. Saya siap membantu Anda dengan informasi tentang UB, AI Center, bantuan personal, atau konsultasi pemilihan jurusan. Ada yang bisa saya bantu hari ini?"

ATURAN PENTING:
- Jika ditanya di luar topik utama, arahkan kembali ke layanan yang tersedia
- Selalu berikan jawaban yang akurat berdasarkan knowledge base
- Jika tidak yakin, katakan "Saya akan bantu cari informasi lebih lanjut" dan sarankan menghubungi pihak terkait
- Hindari jawaban yang terlalu panjang, maksimal 4 kalimat per respons
"""
}]

# HTML Template with improved UI
HTML_PAGE = '''
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BRAVA - Voice Assistant Universitas Brawijaya</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        
        .container {
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            max-width: 800px;
            width: 100%;
            text-align: center;
        }
        
        .header {
            margin-bottom: 30px;
        }
        
        .logo {
            font-size: 2.5rem;
            color: #1e3c72;
            font-weight: bold;
            margin-bottom: 10px;
        }
        
        .subtitle {
            color: #666;
            font-size: 1.1rem;
            margin-bottom: 20px;
        }
        
        .features {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }
        
        .feature-card {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 10px;
            border-left: 4px solid #1e3c72;
        }
        
        .feature-card h4 {
            color: #1e3c72;
            margin-bottom: 5px;
            font-size: 0.9rem;
        }
        
        .feature-card p {
            color: #666;
            font-size: 0.8rem;
        }
        
        .voice-button {
            background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
            color: white;
            border: none;
            padding: 20px 40px;
            font-size: 1.2rem;
            border-radius: 50px;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(76, 175, 80, 0.3);
            margin: 20px 0;
        }
        
        .voice-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(76, 175, 80, 0.4);
        }
        
        .voice-button:active {
            transform: translateY(0);
        }
        
        .status {
            padding: 15px;
            margin: 20px 0;
            border-radius: 10px;
            font-weight: 500;
            min-height: 50px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .listening {
            background: linear-gradient(135deg, #ff9800 0%, #f57c00 100%);
            color: white;
            animation: pulse 2s infinite;
        }
        
        .processing {
            background: linear-gradient(135deg, #2196f3 0%, #1976d2 100%);
            color: white;
        }
        
        .speaking {
            background: linear-gradient(135deg, #4caf50 0%, #388e3c 100%);
            color: white;
        }
        
        .error {
            background: linear-gradient(135deg, #f44336 0%, #d32f2f 100%);
            color: white;
        }
        
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.7; }
            100% { opacity: 1; }
        }
        
        .conversation {
            margin: 20px 0;
            padding: 20px;
            border-radius: 15px;
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            text-align: left;
        }
        
        .message {
            margin: 10px 0;
            padding: 10px 15px;
            border-radius: 10px;
        }
        
        .user-message {
            background: #e3f2fd;
            border-left: 4px solid #2196f3;
        }
        
        .assistant-message {
            background: #e8f5e8;
            border-left: 4px solid #4caf50;
        }
        
        .message-label {
            font-weight: bold;
            margin-bottom: 5px;
        }
        
        .user-label { color: #2196f3; }
        .assistant-label { color: #4caf50; }
        
        audio {
            width: 100%;
            margin-top: 10px;
        }
        
        .conversation-area {
            max-height: 400px;
            overflow-y: auto;
            margin-top: 20px;
        }
        
        .tips {
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            border-radius: 10px;
            padding: 15px;
            margin: 20px 0;
        }
        
        .tips h4 {
            color: #856404;
            margin-bottom: 10px;
        }
        
        .tips ul {
            color: #856404;
            text-align: left;
            padding-left: 20px;
        }
        
        .tips li {
            margin: 5px 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">🎤 BRAVA</div>
            <div class="subtitle">Voice Assistant Universitas Brawijaya</div>
        </div>
        
        <div class="features">
            <div class="feature-card">
                <h4>🏛️ Info Universitas</h4>
                <p>Fakultas, jurusan, dan fasilitas UB</p>
            </div>
            <div class="feature-card">
                <h4>🤖 AI Center</h4>
                <p>Program dan kegiatan AI Center UB</p>
            </div>
            <div class="feature-card">
                <h4>💬 Bantuan Personal</h4>
                <p>Dukungan akademik dan mental</p>
            </div>
            <div class="feature-card">
                <h4>🎯 Konsultasi Jurusan</h4>
                <p>Pilih jurusan sesuai minat & bakat</p>
            </div>
        </div>
        
        <button id="activateBtn" class="voice-button">
            🎤 Mulai Bicara dengan Brava
        </button>
        
        <div id="status" class="status"></div>
        
        <div class="tips">
            <h4>💡 Tips Penggunaan:</h4>
            <ul>
                <li>Klik tombol dan mulai bicara dalam bahasa Indonesia</li>
                <li>Contoh: "Halo Brava, aku mau tanya tentang jurusan Teknik Elektro"</li>
                <li>Atau: "Bantuin aku pilih jurusan yang cocok dong"</li>
                <li>Bicara dengan jelas dan tunggu hingga selesai</li>
            </ul>
        </div>
        
        <div class="conversation-area" id="conversationArea"></div>
    </div>
    
    <script>
        let isProcessing = false;
        
        document.getElementById('activateBtn').addEventListener('click', async function() {
            if (isProcessing) return;
            
            isProcessing = true;
            this.disabled = true;
            this.textContent = '⏳ Sedang Memproses...';
            
            // Remove previous audio elements
            document.querySelectorAll('audio').forEach(audio => audio.remove());
            
            const statusDiv = document.getElementById('status');
            const conversationArea = document.getElementById('conversationArea');
            
            statusDiv.className = 'status listening';
            statusDiv.innerHTML = '🎤 Mendengarkan... Silakan bicara sekarang!';
            
            try {
                // Step 1: Speech Recognition
                const recognitionResponse = await fetch('/recognize', { method: 'POST' });
                const recognitionData = await recognitionResponse.json();
                
                if (!recognitionData.success) {
                    throw new Error(recognitionData.message);
                }
                
                const userInput = recognitionData.text;
                
                // Display user message
                const userMessage = document.createElement('div');
                userMessage.className = 'conversation';
                userMessage.innerHTML = `
                    <div class="message user-message">
                        <div class="message-label user-label">Anda:</div>
                        <div>${userInput}</div>
                    </div>
                `;
                conversationArea.appendChild(userMessage);
                
                statusDiv.className = 'status processing';
                statusDiv.innerHTML = '🔄 Brava sedang memikirkan jawaban...';
                
                // Step 2: Generate AI Response
                const aiResponse = await fetch('/generate-response', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: userInput })
                });
                
                const aiData = await aiResponse.json();
                
                if (!aiData.success) {
                    throw new Error(aiData.message);
                }
                
                const reply = aiData.reply;
                
                // Display assistant message
                const assistantMessage = document.createElement('div');
                assistantMessage.className = 'conversation';
                assistantMessage.innerHTML = `
                    <div class="message assistant-message">
                        <div class="message-label assistant-label">Brava:</div>
                        <div>${reply}</div>
                    </div>
                `;
                conversationArea.appendChild(assistantMessage);
                
                statusDiv.className = 'status processing';
                statusDiv.innerHTML = '🔊 Brava sedang mempersiapkan suara...';
                
                // Step 3: Generate Speech
                const speechResponse = await fetch('/generate-speech', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: reply })
                });
                
                const speechData = await speechResponse.json();
                
                if (!speechData.success) {
                    throw new Error(speechData.message);
                }
                
                // Create audio element
                if (speechData.audio) {
                    const audioElement = document.createElement('audio');
                    audioElement.controls = true;
                    audioElement.autoplay = true;
                    audioElement.src = `data:audio/wav;base64,${speechData.audio}`;
                    assistantMessage.querySelector('.message').appendChild(audioElement);
                    
                    statusDiv.className = 'status speaking';
                    statusDiv.innerHTML = '🔊 Brava sedang berbicara...';
                    
                    audioElement.onended = () => {
                        statusDiv.className = 'status';
                        statusDiv.innerHTML = '✅ Selesai! Klik tombol untuk berbicara lagi.';
                    };
                } else {
                    statusDiv.className = 'status';
                    statusDiv.innerHTML = '✅ Respons selesai! Klik tombol untuk berbicara lagi.';
                }
                
                // Scroll to bottom
                conversationArea.scrollTop = conversationArea.scrollHeight;
                
            } catch (error) {
                statusDiv.className = 'status error';
                statusDiv.innerHTML = `❌ Error: ${error.message}`;
                console.error('Error:', error);
            } finally {
                isProcessing = false;
                this.disabled = false;
                this.textContent = '🎤 Mulai Bicara dengan Brava';
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
                "requestID": "SomeID",
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
                "pluginName": "My Cool Plugin",
                "pluginDeveloper": "My Name",
                "authenticationToken": "82627638ffc6237ddf932c1fd81092b5db7e2c937b56d3324a601ba61636c5d4"
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
    config.speech_recognition_language = "id-ID"
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
        config.speech_synthesis_voice_name = "id-ID-GadisNeural"
        
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
                wf.setframerate(18000)
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

@app.route('/get-knowledge', methods=['GET'])
def get_knowledge():
    """API endpoint to get knowledge base information"""
    return jsonify({
        "success": True,
        "data": UB_KNOWLEDGE_BASE
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "Brava Voice Assistant",
        "version": "1.0.0"
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "message": "Endpoint tidak ditemukan"
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "success": False,
        "message": "Terjadi kesalahan internal server"
    }), 500

if __name__ == '__main__':
    logger.info("Starting Brava Voice Assistant...")
    logger.info("Available endpoints:")
    logger.info("- / : Main interface")
    logger.info("- /recognize : Speech recognition")
    logger.info("- /generate-response : AI response generation")
    logger.info("- /generate-speech : Text-to-speech")
    logger.info("- /get-knowledge : Knowledge base API")
    logger.info("- /health : Health check")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
