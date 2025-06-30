package main

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/pion/webrtc/v4"
	"github.com/pion/webrtc/v4/pkg/media"
	"gopkg.in/hraban/opus.v2"
)

type offer struct {
	Type string `json:"type"`
	SDP  string `json:"sdp"`
}

type answer struct {
	Type string `json:"type"`
	SDP  string `json:"sdp"`
}

var audioTrack *webrtc.TrackLocalStaticSample

func contains(s, substr string) bool {
	return strings.Contains(s, substr)
}


func main() {
	// Create an audio track with Opus codec
	var err error
	audioTrack, err = webrtc.NewTrackLocalStaticSample(
		webrtc.RTPCodecCapability{
			MimeType:    webrtc.MimeTypeOpus,
			ClockRate:   48000,
			Channels:    2,
			// More descriptive SDP line for stereo music
			SDPFmtpLine: "minptime=10;useinbandfec=1;stereo=1;sprop-stereo=1;maxaveragebitrate=128000",
		},
		"audio",
		"pion",
	)
	if err != nil {
		panic(err)
	}

	// Start audio generation in a separate goroutine
	go generateAudio()

	// Set up HTTP server
	http.HandleFunc("/", serveHome)
	http.HandleFunc("/offer", handleOffer)
	http.HandleFunc("/genre", handleGenreChange)

	fmt.Println("WebRTC server started on :8080")
	log.Fatal(http.ListenAndServe(":8080", nil))
}

func generateAudio() {
	pipePath := "/tmp/audio_pipe"
	sampleRate := 48000
	channels := 2
	frameDuration := 20 * time.Millisecond // 20ms frame size
	samplesPerFrame := int(float64(sampleRate) * frameDuration.Seconds()) // 48000 * 0.020 = 960
	bytesPerFrame := samplesPerFrame * channels * 2 // 960 * 2 * 2 = 3840 bytes

	// Create Opus encoder with optimized settings
	encoder, err := opus.NewEncoder(sampleRate, channels, opus.AppAudio)
	if err != nil {
		log.Fatalf("Error creating Opus encoder: %v", err)
	}

	// Increase bitrate to 128kbps for high-quality stereo
	encoder.SetBitrate(128000)
	// Increase complexity for better encoding quality
	// 8 is a good balance for music
	encoder.SetComplexity(8)
	encoder.SetInBandFEC(true) // Forward Error Correction is great for WebRTC
	encoder.SetPacketLossPerc(5)

	// Buffers for processing
	pcmBuffer := make([]byte, bytesPerFrame)
	pcmInt16 := make([]int16, samplesPerFrame*channels)
	opusBuffer := make([]byte, 4000) // A safe, large buffer for Opus data

	// The Ticker is our pacemaker. It will fire every 20ms.
	ticker := time.NewTicker(frameDuration)
	defer ticker.Stop()

	// Loop to connect and read from the pipe
	for {
		log.Printf("Waiting for audio pipe at %s...", pipePath)
		pipe, err := os.Open(pipePath)
		if err != nil {
			log.Printf("Error opening pipe: %v. Retrying in 2s.", err)
			time.Sleep(2 * time.Second)
			continue
		}
		defer pipe.Close()

		log.Println("Connected to audio pipe. Starting paced audio stream.")

		// The main paced loop. It waits for the ticker to fire.
		for range ticker.C {
			// Read a full frame's worth of PCM data.
			// This will block until the Python script writes data, which is what we want.
			// If the Python script is slow, this loop will wait for it.
			_, err := io.ReadFull(pipe, pcmBuffer)
			if err != nil {
				log.Printf("Error reading from pipe: %v. Will attempt to reconnect.", err)
				break // Break inner loop to trigger reconnection
			}

			// Convert raw bytes (Little Endian) to int16 samples
			for i := 0; i < len(pcmInt16); i++ {
				pcmInt16[i] = int16(binary.LittleEndian.Uint16(pcmBuffer[i*2:]))
			}

			// Encode the PCM data to Opus
			n, err := encoder.Encode(pcmInt16, opusBuffer)
			if err != nil {
				log.Printf("Error encoding to Opus: %v", err)
				continue
			}

			// Write the encoded Opus sample to our WebRTC track
			// The Pion library handles the RTP timestamping based on the sample duration.
			if err := audioTrack.WriteSample(media.Sample{
				Data:     opusBuffer[:n],
				Duration: frameDuration,
			}); err != nil {
				// This error can happen if the peer connection is closed.
				// It's often not critical, but we log it.
				// log.Printf("Warning: Error writing sample: %v", err)
			}
		}

		// If we broke out of the inner loop, close the current pipe and try to reopen.
		pipe.Close()
	}
}


func handleOffer(w http.ResponseWriter, r *http.Request) {
	// Handle CORS preflight
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
	
	log.Printf("Received %s request from %s", r.Method, r.RemoteAddr)
	
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusOK)
		return
	}
	
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Read the offer from the request body
	body, err := io.ReadAll(r.Body)
	if err != nil {
		log.Printf("Error reading request body: %v", err)
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	var o offer
	if err := json.Unmarshal(body, &o); err != nil {
		log.Printf("Error unmarshaling offer: %v", err)
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	
	log.Printf("Received offer type: %s", o.Type)
	log.Printf("SDP length: %d characters", len(o.SDP))
	
	// Check if SDP contains ice-ufrag
	if !contains(o.SDP, "ice-ufrag") {
		log.Printf("WARNING: SDP missing ice-ufrag, this might be a Safari issue")
	}

	// Prepare the configuration
	config := webrtc.Configuration{
		ICEServers: []webrtc.ICEServer{
			{
				URLs: []string{"stun:stun.l.google.com:19302"},
			},
		},
	}
	
	// Create a SettingEngine to allow non-localhost connections
	settingEngine := webrtc.SettingEngine{}
	settingEngine.SetNetworkTypes([]webrtc.NetworkType{
		webrtc.NetworkTypeUDP4,
		webrtc.NetworkTypeUDP6,
		webrtc.NetworkTypeTCP4,
		webrtc.NetworkTypeTCP6,
	})
	
	// Set NAT1To1IPs to help with connectivity
	// Use HOST_IP environment variable if set
	if hostIP := os.Getenv("HOST_IP"); hostIP != "" {
		log.Printf("Using HOST_IP: %s for ICE candidates", hostIP)
		settingEngine.SetNAT1To1IPs([]string{hostIP}, webrtc.ICECandidateTypeHost)
	} else {
		// Let WebRTC figure out the IPs
		settingEngine.SetNAT1To1IPs([]string{}, webrtc.ICECandidateTypeHost)
	}
	
	// Configure larger receive buffer for smoother playback
	settingEngine.SetReceiveMTU(1600) // Larger MTU for better throughput
	
	// Create API with settings
	m := &webrtc.MediaEngine{}
	if err := m.RegisterDefaultCodecs(); err != nil {
		log.Printf("Error registering codecs: %v", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	
	api := webrtc.NewAPI(
		webrtc.WithMediaEngine(m),
		webrtc.WithSettingEngine(settingEngine),
	)

	// Create a new RTCPeerConnection for this request
	peerConnection, err := api.NewPeerConnection(config)
	if err != nil {
		log.Printf("Error creating peer connection: %v", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	// Add the audio track to the peer connection
	rtpSender, err := peerConnection.AddTrack(audioTrack)
	if err != nil {
		log.Printf("Error adding track: %v", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	// Read incoming RTCP packets
	go func() {
		rtcpBuf := make([]byte, 1500)
		for {
			if _, _, rtcpErr := rtpSender.Read(rtcpBuf); rtcpErr != nil {
				return
			}
		}
	}()

	// Set the handler for ICE connection state
	peerConnection.OnICEConnectionStateChange(func(connectionState webrtc.ICEConnectionState) {
		fmt.Printf("Connection State has changed %s \n", connectionState.String())
	})

	// Set the handler for Peer connection state
	peerConnection.OnConnectionStateChange(func(s webrtc.PeerConnectionState) {
		fmt.Printf("Peer Connection State has changed: %s\n", s.String())
	})
	
	// Log ICE candidates for debugging
	peerConnection.OnICECandidate(func(candidate *webrtc.ICECandidate) {
		if candidate != nil {
			log.Printf("ICE candidate: %s", candidate.String())
		}
	})

	// Set the remote SessionDescription
	if err := peerConnection.SetRemoteDescription(webrtc.SessionDescription{
		Type: webrtc.SDPTypeOffer,
		SDP:  o.SDP,
	}); err != nil {
		log.Printf("Error setting remote description: %v", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	// Create an answer
	answerSDP, err := peerConnection.CreateAnswer(nil)
	if err != nil {
		log.Printf("Error creating answer: %v", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	// Create channel that is blocked until ICE Gathering is complete
	gatherComplete := webrtc.GatheringCompletePromise(peerConnection)

	// Sets the LocalDescription, and starts our UDP listeners
	if err := peerConnection.SetLocalDescription(answerSDP); err != nil {
		log.Printf("Error setting local description: %v", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	// Block until ICE Gathering is complete, disabling trickle ICE
	<-gatherComplete

	// Send the answer
	response := answer{
		Type: "answer",
		SDP:  peerConnection.LocalDescription().SDP,
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(response); err != nil {
		log.Printf("Error encoding response: %v", err)
	} else {
		log.Printf("Successfully sent answer to %s", r.RemoteAddr)
	}
}

func handleGenreChange(w http.ResponseWriter, r *http.Request) {
	// Handle CORS
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
	
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusOK)
		return
	}
	
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	
	// Parse the request body
	var req struct {
		Genre string `json:"genre"`
	}
	
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}
	
	log.Printf("Genre change requested: %s", req.Genre)
	
	// Write genre to a file that Python will monitor
	genreFile := "/tmp/genre_request.txt"
	if err := os.WriteFile(genreFile, []byte(req.Genre), 0644); err != nil {
		log.Printf("Error writing genre file: %v", err)
		http.Error(w, "Failed to change genre", http.StatusInternalServerError)
		return
	}
	
	// Send success response
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"status": "success",
		"genre": req.Genre,
	})
}

func serveHome(w http.ResponseWriter, r *http.Request) {
    w.Header().Set("Content-Type", "text/html")
    // Using a raw string literal `` makes embedding large HTML blocks much easier
    fmt.Fprint(w, `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ChobinBeats - Generative Music</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --bg-color: #121212;
            --surface-color: #1e1e1e;
            --primary-color: #bb86fc;
            --primary-variant: #3700b3;
            --secondary-color: #03dac6;
            --text-color: #e0e0e0;
            --text-secondary: #a0a0a0;
            --border-color: #333333;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Poppins', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
            background-image: radial-gradient(circle at center, rgba(187, 134, 252, 0.1), transparent 50%);
        }

        .container {
            width: 100%;
            max-width: 600px;
            background-color: var(--surface-color);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 40px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(10px);
            background-color: rgba(30, 30, 30, 0.75);
            text-align: center;
        }

        header h1 {
            font-size: 2.5rem;
            font-weight: 700;
            color: var(--primary-color);
            margin-bottom: 5px;
        }

        header p {
            font-size: 1.1rem;
            color: var(--text-secondary);
            margin-bottom: 30px;
        }


        #playPauseBtn {
            width: 80px;
            height: 80px;
            border-radius: 50%;
            border: none;
            background: linear-gradient(145deg, var(--primary-variant), var(--primary-color));
            color: white;
            font-size: 2rem;
            cursor: pointer;
            display: flex;
            justify-content: center;
            align-items: center;
            margin: 0 auto;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(187, 134, 252, 0.4);
        }

        #playPauseBtn:hover {
            transform: scale(1.1);
            box-shadow: 0 6px 20px rgba(187, 134, 252, 0.6);
        }

        #playPauseBtn:disabled {
            background: #555;
            cursor: not-allowed;
            box-shadow: none;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .fa-spinner {
            animation: spin 1s linear infinite;
        }

        #status {
            margin-top: 20px;
            height: 24px;
            font-size: 1.1rem;
            color: var(--secondary-color);
            font-weight: 600;
        }

        .genre-section {
            margin-top: 40px;
            padding-top: 30px;
            border-top: 1px solid var(--border-color);
        }

        .genre-section h2 {
            font-weight: 600;
            margin-bottom: 20px;
        }

        .genre-grid {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 12px;
        }

        .genre-btn {
            background-color: rgba(255, 255, 255, 0.1);
            color: var(--text-color);
            padding: 8px 18px;
            font-size: 0.9rem;
            font-weight: 400;
            border: 1px solid var(--border-color);
            border-radius: 20px;
            cursor: pointer;
            transition: all 0.3s ease;
        }

        .genre-btn:hover, .genre-btn.active {
            background-color: var(--primary-color);
            color: var(--bg-color);
            border-color: var(--primary-color);
            font-weight: 600;
        }

        .custom-genre-container {
            margin-top: 30px;
        }
        
        .custom-genre-form {
            display: flex;
            gap: 10px;
            justify-content: center;
        }

        .custom-genre-input {
            flex-grow: 1;
            max-width: 300px;
            padding: 10px 15px;
            font-size: 1rem;
            background-color: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--border-color);
            color: var(--text-color);
            border-radius: 8px;
        }

        .custom-genre-input:focus {
            outline: none;
            border-color: var(--primary-color);
        }

        .custom-genre-btn {
            background-color: var(--secondary-color);
            color: var(--bg-color);
            padding: 10px 20px;
            font-size: 1rem;
            font-weight: 600;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .custom-genre-btn:hover {
            opacity: 0.9;
        }

        /* Hide the default audio player */
        audio {
            display: none;
        }

    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>ChobinBeats</h1>
            <p>Infinite Generative Music</p>
        </header>

        <main>
            <button id="playPauseBtn"><i class="fas fa-play"></i></button>
            <div id="status">Ready to Stream</div>
        </main>
        
        <audio id="remoteAudio" autoplay></audio>
        
        <div class="genre-section">
            <h2>Select a Genre</h2>
            <div class="genre-grid">
                <button class="genre-btn active" onclick="changeGenre('synthwave', event)">Synthwave</button>
                <button class="genre-btn" onclick="changeGenre('disco funk', event)">Disco Funk</button>
                <button class="genre-btn" onclick="changeGenre('cello', event)">Cello</button>
                <button class="genre-btn" onclick="changeGenre('jazz', event)">Jazz</button>
                <button class="genre-btn" onclick="changeGenre('rock', event)">Rock</button>
                <button class="genre-btn" onclick="changeGenre('classical', event)">Classical</button>
                <button class="genre-btn" onclick="changeGenre('ambient', event)">Ambient</button>
                <button class="genre-btn" onclick="changeGenre('hip hop', event)">Hip Hop</button>
            </div>
            <div class="custom-genre-container">
                 <div class="custom-genre-form">
                    <input type="text" id="customGenreInput" class="custom-genre-input" placeholder="Or create your own..." onkeypress="handleCustomGenreKeyPress(event)">
                    <button class="custom-genre-btn" onclick="submitCustomGenre()">Create</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        // DOM Elements
        const playPauseBtn = document.getElementById('playPauseBtn');
        const playPauseIcon = playPauseBtn.querySelector('i');
        const statusDiv = document.getElementById('status');
        const remoteAudio = document.getElementById('remoteAudio');
        
        // WebRTC & State
        let pc;
        let isPlaying = false;
        let isConnecting = false;
        let currentGenre = 'synthwave';


        playPauseBtn.onclick = () => {
            if (isConnecting) return;

            if (!pc) {
                startConnection();
            } else {
                togglePlayPause();
            }
        };

        function togglePlayPause() {
            if (isPlaying) {
                remoteAudio.pause();
                isPlaying = false;
                playPauseIcon.className = 'fas fa-play';
                updateStatus('Paused');
            } else {
                remoteAudio.play();
                isPlaying = true;
                playPauseIcon.className = 'fas fa-pause';
                updateStatus('Now Playing: ' + currentGenre);
            }
        }

        async function startConnection() {
            isConnecting = true;
            playPauseBtn.disabled = true;
            playPauseIcon.className = 'fas fa-spinner';
            updateStatus('Connecting...');

            try {
                pc = new RTCPeerConnection({
                    iceServers: [{urls: 'stun:stun.l.google.com:19302'}]
                });

                pc.ontrack = (event) => {
                    if (event.track.kind === 'audio') {
                        remoteAudio.srcObject = event.streams[0];
                    }
                };

                remoteAudio.onplaying = () => {
                    isConnecting = false;
                    isPlaying = true;
                    playPauseBtn.disabled = false;
                    playPauseIcon.className = 'fas fa-pause';
                    updateStatus('Now Playing: ' + currentGenre);
                };

                pc.oniceconnectionstatechange = () => {
                    if (pc.iceConnectionState === 'failed' || pc.iceConnectionState === 'disconnected' || pc.iceConnectionState === 'closed') {
                        isConnecting = false;
                        isPlaying = false;
                        playPauseBtn.disabled = false;
                        playPauseIcon.className = 'fas fa-play';
                        updateStatus('Connection lost. Please try again.');
                        if (pc) {
                            pc.close();
                            pc = null;
                        }
                    }
                };

                pc.addTransceiver('audio', { direction: 'recvonly' });
                
                const offer = await pc.createOffer();
                await pc.setLocalDescription(offer);
                
                await new Promise(resolve => {
                    if (pc.iceGatheringState === 'complete') {
                        resolve();
                    } else {
                        pc.addEventListener('icegatheringstatechange', () => {
                            if (pc.iceGatheringState === 'complete') {
                                resolve();
                            }
                        }, { once: true });
                        // Also resolve after a timeout to avoid hanging
                        setTimeout(resolve, 1000);
                    }
                });
                
                const response = await fetch('/offer', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(pc.localDescription)
                });

                if (!response.ok) throw new Error('Server failed to provide an answer.');

                const answer = await response.json();
                await pc.setRemoteDescription(new RTCSessionDescription(answer));
                
            } catch (error) {
                console.error('Connection Error:', error);
                updateStatus('Error: ' + error.message);
                isConnecting = false;
                playPauseBtn.disabled = false;
                playPauseIcon.className = 'fas fa-play';
                pc = null;
            }
        }

        function updateStatus(message) {
            statusDiv.textContent = message;
        }

        async function changeGenre(genre, event) {
            // Update UI for preset buttons
            if (event) {
                document.querySelectorAll('.genre-btn').forEach(btn => btn.classList.remove('active'));
                event.target.classList.add('active');
            }
            // Clear custom input if a preset is clicked
            document.getElementById('customGenreInput').value = '';
            
            await sendGenreRequest(genre);
        }

        function submitCustomGenre() {
            const input = document.getElementById('customGenreInput');
            const customGenre = input.value.trim();
            if (!customGenre) {
                alert('Please enter a custom genre.');
                return;
            }
            // Clear preset button selections
            document.querySelectorAll('.genre-btn').forEach(btn => btn.classList.remove('active'));
            sendGenreRequest(customGenre);
        }

        function handleCustomGenreKeyPress(event) {
            if (event.key === 'Enter') {
                submitCustomGenre();
            }
        }

        async function sendGenreRequest(genre) {
            currentGenre = genre;
            if (isPlaying) {
                updateStatus('Now Playing: ' + genre);
            }

            try {
                const response = await fetch('/genre', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ genre: genre })
                });
                if (!response.ok) throw new Error('Server request failed.');
                console.log('Genre change request sent for:', genre);
            } catch (error) {
                console.error('Error changing genre:', error);
                updateStatus('Failed to change genre.');
            }
        }


    </script>
</body>
</html>`)
}