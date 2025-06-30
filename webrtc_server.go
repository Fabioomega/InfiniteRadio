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
	fmt.Fprintf(w, `<!DOCTYPE html>
<html>
<head>
    <title>ChobinBeats WebRTC Audio Test</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f0f0f0;
        }
        .container {
            background-color: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            text-align: center;
        }
        button {
            background-color: #4CAF50;
            color: white;
            padding: 12px 24px;
            font-size: 16px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            display: block;
            margin: 20px auto;
        }
        button:hover {
            background-color: #45a049;
        }
        button:disabled {
            background-color: #cccccc;
            cursor: not-allowed;
        }
        #status {
            text-align: center;
            margin: 20px 0;
            font-weight: bold;
        }
        .success { color: #4CAF50; }
        .error { color: #f44336; }
        .info { color: #2196F3; }
        audio {
            width: 100%%;
            margin-top: 20px;
        }
        .genre-section {
            margin: 30px 0;
            padding: 20px;
            background-color: #f9f9f9;
            border-radius: 8px;
        }
        .genre-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
            gap: 10px;
            margin: 15px 0;
        }
        .genre-btn {
            background-color: #2196F3;
            color: white;
            padding: 10px 15px;
            font-size: 14px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            transition: all 0.3s;
        }
        .genre-btn:hover {
            background-color: #1976D2;
            transform: translateY(-2px);
        }
        .genre-btn.active {
            background-color: #4CAF50;
        }
        #currentGenre {
            text-align: center;
            font-size: 18px;
            color: #4CAF50;
            margin: 10px 0;
        }
        .custom-genre-container {
            margin-top: 20px;
            padding: 15px;
            background-color: #e8e8e8;
            border-radius: 8px;
            text-align: center;
        }
        .custom-genre-input {
            padding: 10px;
            font-size: 14px;
            border: 2px solid #ddd;
            border-radius: 5px;
            width: 200px;
            margin-right: 10px;
        }
        .custom-genre-input:focus {
            outline: none;
            border-color: #2196F3;
        }
        .custom-genre-btn {
            background-color: #FF9800;
            color: white;
            padding: 10px 20px;
            font-size: 14px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            transition: all 0.3s;
        }
        .custom-genre-btn:hover {
            background-color: #F57C00;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎵 ChobinBeats WebRTC Audio Test</h1>
        <p style="text-align: center;">Click the button below to start receiving audio from the server</p>
        
        <button id="startButton" onclick="startConnection()">Start Audio Stream</button>
        
        <div id="status" class="info">Ready to connect</div>
        
        <audio id="remoteAudio" controls autoplay></audio>
        
        <div class="genre-section">
            <h2 style="text-align: center;">Music Genre Selection</h2>
            <div id="currentGenre">Current Genre: synthwave</div>
            <div class="genre-grid">
                <button class="genre-btn" onclick="changeGenre('synthwave')">Synthwave</button>
                <button class="genre-btn" onclick="changeGenre('disco funk')">Disco Funk</button>
                <button class="genre-btn" onclick="changeGenre('cello')">Cello</button>
                <button class="genre-btn" onclick="changeGenre('jazz')">Jazz</button>
                <button class="genre-btn" onclick="changeGenre('rock')">Rock</button>
                <button class="genre-btn" onclick="changeGenre('classical')">Classical</button>
                <button class="genre-btn" onclick="changeGenre('ambient')">Ambient</button>
                <button class="genre-btn" onclick="changeGenre('electronic')">Electronic</button>
                <button class="genre-btn" onclick="changeGenre('hip hop')">Hip Hop</button>
                <button class="genre-btn" onclick="changeGenre('reggae')">Reggae</button>
                <button class="genre-btn" onclick="changeGenre('country')">Country</button>
                <button class="genre-btn" onclick="changeGenre('blues')">Blues</button>
            </div>
            <div class="custom-genre-container">
                <h3 style="margin-top: 0;">Custom Genre</h3>
                <p style="margin: 10px 0; color: #666;">Enter any custom genre or style description:</p>
                <input type="text" id="customGenreInput" class="custom-genre-input" placeholder="e.g. 'dark techno', '80s pop'" onkeypress="handleCustomGenreKeyPress(event)">
                <button class="custom-genre-btn" onclick="submitCustomGenre()">Apply Custom Genre</button>
            </div>
        </div>
    </div>

    <script>
        let pc;
        let remoteAudio = document.getElementById('remoteAudio');
        let statusDiv = document.getElementById('status');
        let startButton = document.getElementById('startButton');

        async function startConnection() {
            try {
                startButton.disabled = true;
                updateStatus('Creating connection...', 'info');
                
                // Create peer connection
                pc = new RTCPeerConnection({
                    iceServers: [{urls: 'stun:stun.l.google.com:19302'}]
                });

                // Handle incoming audio tracks
                pc.ontrack = (event) => {
                    console.log('Received remote track:', event.track);
                    console.log('Track readyState:', event.track.readyState);
                    console.log('Track muted:', event.track.muted);
                    if (event.track.kind === 'audio') {
                        remoteAudio.srcObject = event.streams[0];
                        updateStatus('Audio stream connected! You should hear audio now.', 'success');
                        
                        // Debug audio levels
                        event.track.onunmute = () => console.log('Track unmuted');
                        event.track.onmute = () => console.log('Track muted');
                        event.track.onended = () => console.log('Track ended');
                    }
                };

                // Monitor connection state
                pc.oniceconnectionstatechange = () => {
                    console.log('ICE connection state:', pc.iceConnectionState);
                    if (pc.iceConnectionState === 'connected') {
                        updateStatus('Connection established!', 'success');
                    } else if (pc.iceConnectionState === 'failed') {
                        updateStatus('Connection failed', 'error');
                        startButton.disabled = false;
                    }
                };

                // Add a transceiver for audio to ensure proper SDP generation
                pc.addTransceiver('audio', { direction: 'recvonly' });
                
                // Create offer
                updateStatus('Creating offer...', 'info');
                const offer = await pc.createOffer();
                
                await pc.setLocalDescription(offer);
                
                // Wait for ICE gathering to start
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
                
                // Send offer to server
                updateStatus('Sending offer to server...', 'info');
                const response = await fetch('/offer', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        type: pc.localDescription.type,
                        sdp: pc.localDescription.sdp
                    })
                });

                if (!response.ok) {
                    throw new Error('Failed to get answer from server');
                }

                const answer = await response.json();
                
                // Set remote description
                updateStatus('Setting remote description...', 'info');
                await pc.setRemoteDescription(new RTCSessionDescription(answer));
                
                updateStatus('Waiting for connection...', 'info');
                
            } catch (error) {
                console.error('Error:', error);
                updateStatus('Error: ' + error.message, 'error');
                startButton.disabled = false;
            }
        }

        function updateStatus(message, className) {
            statusDiv.textContent = message;
            statusDiv.className = className;
        }

        let currentGenre = 'synthwave';
        
        async function changeGenre(genre) {
            try {
                // Update UI
                currentGenre = genre;
                document.getElementById('currentGenre').textContent = 'Current Genre: ' + genre;
                
                // Update button states
                document.querySelectorAll('.genre-btn').forEach(btn => {
                    btn.classList.remove('active');
                });
                event.target.classList.add('active');
                
                // Send POST request to server
                const response = await fetch('/genre', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ genre: genre })
                });
                
                if (!response.ok) {
                    throw new Error('Failed to change genre');
                }
                
                const result = await response.json();
                console.log('Genre changed:', result);
                
            } catch (error) {
                console.error('Error changing genre:', error);
                alert('Failed to change genre: ' + error.message);
            }
        }
        
        function submitCustomGenre() {
            const input = document.getElementById('customGenreInput');
            const customGenre = input.value.trim();
            
            if (!customGenre) {
                alert('Please enter a custom genre');
                return;
            }
            
            // Clear preset button selections
            document.querySelectorAll('.genre-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            
            // Use the changeGenre function but without the event target
            changeGenreCustom(customGenre);
        }
        
        function handleCustomGenreKeyPress(event) {
            if (event.key === 'Enter') {
                submitCustomGenre();
            }
        }
        
        async function changeGenreCustom(genre) {
            try {
                // Update UI
                currentGenre = genre;
                document.getElementById('currentGenre').textContent = 'Current Genre: ' + genre;
                
                // Send POST request to server
                const response = await fetch('/genre', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ genre: genre })
                });
                
                if (!response.ok) {
                    throw new Error('Failed to change genre');
                }
                
                const result = await response.json();
                console.log('Genre changed:', result);
                
            } catch (error) {
                console.error('Error changing genre:', error);
                alert('Failed to change genre: ' + error.message);
            }
        }
    </script>
</body>
</html>`)
}