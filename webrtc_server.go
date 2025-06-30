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
			SDPFmtpLine: "minptime=10;useinbandfec=1",
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

	encoder.SetBitrate(96000)
	encoder.SetComplexity(1)
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
    </style>
</head>
<body>
    <div class="container">
        <h1>🎵 ChobinBeats WebRTC Audio Test</h1>
        <p style="text-align: center;">Click the button below to start receiving audio from the server</p>
        
        <button id="startButton" onclick="startConnection()">Start Audio Stream</button>
        
        <div id="status" class="info">Ready to connect</div>
        
        <audio id="remoteAudio" controls autoplay></audio>
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
    </script>
</body>
</html>`)
}