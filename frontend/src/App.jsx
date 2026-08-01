import { useEffect, useMemo, useRef, useState } from 'react';

const QUALITY_OPTIONS = [
  'COMPACT_SIZE',
  'COMPACT_SIZE_SPEECH',
  'COMPACT_SIZE_MUSIC',
  'COMPACT_MUSIC_INSTRUMENTAL',
  'WHATSAPP',
  'MUSIC_CONCERT',
  'YOUTUBE_UPLOAD',
];

const API_BASE = '/api';
const INTERIM_COMMIT_DELAY_MS = 1200;

function extractVideoId(value) {
  const input = value.trim();
  const urlMatch = input.match(/(?:v=|youtu\.be\/)([A-Za-z0-9_-]{11})/);
  if (urlMatch) return urlMatch[1];
  return input;
}

function App() {
  const [activeView, setActiveView] = useState('download');
  const [videoInput, setVideoInput] = useState('');
  const [quality, setQuality] = useState('COMPACT_SIZE_SPEECH');
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [info, setInfo] = useState('Ready');
  const [error, setError] = useState('');
  const [logs, setLogs] = useState([]);

  const [isListening, setIsListening] = useState(false);
  const [transcriptText, setTranscriptText] = useState('');
  const [interimText, setInterimText] = useState('');
  const [transcriptionStatus, setTranscriptionStatus] = useState('Ready');
  const [transcriptionError, setTranscriptionError] = useState('');
  const [translatedTextByLanguage, setTranslatedTextByLanguage] = useState({});
  const [translationError, setTranslationError] = useState('');
  const [selectedLanguage, setSelectedLanguage] = useState('en-US');
  const [selectedTranslationTargets, setSelectedTranslationTargets] = useState(['hi']);
  const [pauseCommitMs, setPauseCommitMs] = useState(INTERIM_COMMIT_DELAY_MS);
  const recognitionRef = useRef(null);
  const shouldKeepListeningRef = useRef(false);
  const transcriptInterimTimerRef = useRef(null);
  const lastTranscriptCommittedRef = useRef('');

  const [cameraEnabled, setCameraEnabled] = useState(false);
  const [cameraError, setCameraError] = useState('');
  const [cameraSubtitle, setCameraSubtitle] = useState('');
  const [cameraInterimText, setCameraInterimText] = useState('');
  const [cameraStatus, setCameraStatus] = useState('Ready');
  const [cameraSourceLanguage, setCameraSourceLanguage] = useState('en-US');
  const [cameraTargetLanguage, setCameraTargetLanguage] = useState('hi');
  const [isCameraListening, setIsCameraListening] = useState(false);
  const [isVlcStreaming, setIsVlcStreaming] = useState(false);
  const [vlcStatus, setVlcStatus] = useState('Relay stopped');
  const [vlcError, setVlcError] = useState('');
  const [vlcUrl, setVlcUrl] = useState('udp://@127.0.0.1:1234');
  const cameraVideoRef = useRef(null);
  const cameraStreamRef = useRef(null);
  const cameraRecognitionRef = useRef(null);
  const shouldKeepCameraListeningRef = useRef(false);
  const cameraInterimTimerRef = useRef(null);
  const lastCameraCommittedRef = useRef('');
  const vlcWebSocketRef = useRef(null);
  const vlcMediaRecorderRef = useRef(null);

  const languageOptions = [
    { value: 'en-US', label: 'English (US)' },
    { value: 'en-IN', label: 'English (India)' },
    { value: 'hi-IN', label: 'Hindi' },
    { value: 'te-IN', label: 'Telugu' },
    { value: 'ta-IN', label: 'Tamil' },
    { value: 'ml-IN', label: 'Malayalam' },
    { value: 'kn-IN', label: 'Kannada' },
  ];

  const translationOptions = [
    { value: 'en', label: 'English' },
    { value: 'hi', label: 'Hindi' },
    { value: 'te', label: 'Telugu' },
    { value: 'ta', label: 'Tamil' },
    { value: 'ml', label: 'Malayalam' },
    { value: 'kn', label: 'Kannada' },
  ];

  const canSubmit = useMemo(() => videoInput.trim().length > 0 && !isRunning, [videoInput, isRunning]);

  function getSourceLanguageCode(locale) {
    return locale.split('-')[0]?.toLowerCase() || 'auto';
  }

  function toggleTranslationTarget(languageCode) {
    setSelectedTranslationTargets((prev) => {
      if (prev.includes(languageCode)) {
        if (prev.length === 1) {
          return prev;
        }
        return prev.filter((item) => item !== languageCode);
      }
      return [...prev, languageCode];
    });
  }

  useEffect(() => {
    return () => {
      shouldKeepListeningRef.current = false;
      shouldKeepCameraListeningRef.current = false;
      if (transcriptInterimTimerRef.current) {
        window.clearTimeout(transcriptInterimTimerRef.current);
        transcriptInterimTimerRef.current = null;
      }
      if (cameraInterimTimerRef.current) {
        window.clearTimeout(cameraInterimTimerRef.current);
        cameraInterimTimerRef.current = null;
      }
      recognitionRef.current?.stop();
      cameraRecognitionRef.current?.stop();
      cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
      vlcMediaRecorderRef.current?.stop();
      if (vlcWebSocketRef.current) {
        vlcWebSocketRef.current.close();
      }
    };
  }, []);

  useEffect(() => {
    if (activeView === 'cameraTranslate') {
      return;
    }

    shouldKeepCameraListeningRef.current = false;
    cameraRecognitionRef.current?.stop();
    cameraRecognitionRef.current = null;
    setIsCameraListening(false);
    if (vlcMediaRecorderRef.current) {
      vlcMediaRecorderRef.current.stop();
      vlcMediaRecorderRef.current = null;
    }
    if (vlcWebSocketRef.current) {
      vlcWebSocketRef.current.close();
      vlcWebSocketRef.current = null;
    }
    setIsVlcStreaming(false);
    void fetch(`${API_BASE}/vlc-stream/stop`, { method: 'POST' }).catch(() => {});
    if (cameraStreamRef.current) {
      cameraStreamRef.current.getTracks().forEach((track) => track.stop());
      cameraStreamRef.current = null;
    }
    setCameraEnabled(false);
  }, [activeView]);

  async function handleStart(event) {
    event.preventDefault();

    const videoId = extractVideoId(videoInput);
    if (!videoId || videoId.length < 11) {
      setError('Enter a valid YouTube Video ID or URL.');
      return;
    }

    setIsRunning(true);
    setProgress(0);
    setInfo('Starting download...');
    setError('');
    setLogs([]);

    try {
      const query = new URLSearchParams({
        video_id: videoId,
        quality,
        output_format: 'm4a',
      });

      const response = await fetch(`${API_BASE}/download-audio/stream?${query.toString()}`);
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || 'Failed to start download process.');
      }

      if (!response.body) {
        throw new Error('Streaming not supported by browser response.');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() || '';

        for (const eventChunk of events) {
          const dataLine = eventChunk
            .split('\n')
            .find((line) => line.startsWith('data: '));

          if (!dataLine) continue;

          const payload = JSON.parse(dataLine.slice(6));
          setLogs((prev) => [...prev, payload.message]);

          if (typeof payload.progress === 'number') {
            setProgress((prev) => Math.max(prev, payload.progress));
          }

          if (payload.type === 'error' || payload.type === 'failed') {
            setError(payload.message);
          } else {
            setInfo(payload.message);
          }
        }
      }
    } catch (err) {
      setError(err.message || 'Unexpected error while downloading audio.');
      setInfo('Failed');
    } finally {
      setIsRunning(false);
    }
  }

  async function requestTranslations(text, sourceLanguage, targetLanguages) {
    if (!text?.trim()) return;
    if (!targetLanguages.length) return;

    const params = new URLSearchParams({
      text,
      source_language: sourceLanguage,
      target_languages: targetLanguages.join(','),
    });

    try {
      const response = await fetch(`${API_BASE}/translate-text?${params.toString()}`);
      const payload = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(payload.error || 'Translation request failed.');
      }

      return payload.translations || {};
    } catch (err) {
      throw new Error(err.message || 'Translation failed.');
    }
  }

  async function translateTextChunk(text, sourceLanguage, targetLanguages) {
    if (!text?.trim()) return;

    try {
      const translatedMap = await requestTranslations(text, sourceLanguage, targetLanguages);

      setTranslatedTextByLanguage((prev) => {
        const next = { ...prev };
        targetLanguages.forEach((lang) => {
          const translated = translatedMap[lang]?.trim();
          if (!translated) {
            return;
          }
          const existingText = next[lang] || '';
          next[lang] = !existingText
            ? `${translated}\n`
            : `${existingText}${existingText.endsWith('\n') ? '' : '\n'}${translated}\n`;
        });
        return next;
      });
      setTranslationError('');
    } catch (err) {
      setTranslationError(err.message);
    }
  }

  function commitTranscriptChunk(text) {
    const cleaned = text.trim();
    if (!cleaned) return;
    if (cleaned === lastTranscriptCommittedRef.current) return;

    lastTranscriptCommittedRef.current = cleaned;
    setInterimText('');
    setTranscriptText((prev) => {
      if (!prev) return `${cleaned}\n`;
      return `${prev}${prev.endsWith('\n') ? '' : '\n'}${cleaned}\n`;
    });
    void translateTextChunk(cleaned, getSourceLanguageCode(selectedLanguage), selectedTranslationTargets);
    setTranscriptionStatus('Captured live transcript');
  }

  function commitCameraSubtitle(text) {
    const cleaned = text.trim();
    if (!cleaned) return;
    if (cleaned === lastCameraCommittedRef.current) return;

    lastCameraCommittedRef.current = cleaned;
    setCameraInterimText('');
    void (async () => {
      try {
        const translatedMap = await requestTranslations(
          cleaned,
          getSourceLanguageCode(cameraSourceLanguage),
          [cameraTargetLanguage]
        );
        const translated = translatedMap[cameraTargetLanguage]?.trim() || cleaned;
        setCameraSubtitle(translated);
        setCameraStatus('Subtitle updated');
        setCameraError('');
      } catch (err) {
        setCameraSubtitle(cleaned);
        setCameraError(err.message || 'Live subtitle translation failed.');
        setCameraStatus('Showing source subtitle');
      }
    })();
  }

  function startListening() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setTranscriptionError('Speech recognition is not available in this browser. Try Chrome or Edge.');
      return;
    }

    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = selectedLanguage;
    shouldKeepListeningRef.current = true;

    recognition.onresult = (event) => {
      let interimSpeech = '';
      let finalSpeech = '';

      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const text = result[0].transcript.trim();

        if (result.isFinal) {
          finalSpeech += `${text} `;
        } else {
          interimSpeech += `${text} `;
        }
      }

      if (interimSpeech.trim()) {
        setInterimText(interimSpeech.trim());
        if (transcriptInterimTimerRef.current) {
          window.clearTimeout(transcriptInterimTimerRef.current);
        }
        transcriptInterimTimerRef.current = window.setTimeout(() => {
          commitTranscriptChunk(interimSpeech);
          transcriptInterimTimerRef.current = null;
        }, pauseCommitMs);
      } else {
        setInterimText('');
      }

      if (finalSpeech.trim()) {
        if (transcriptInterimTimerRef.current) {
          window.clearTimeout(transcriptInterimTimerRef.current);
          transcriptInterimTimerRef.current = null;
        }
        commitTranscriptChunk(finalSpeech);
      }
    };

    recognition.onerror = (event) => {
      if (event.error === 'no-speech') {
        setTranscriptionStatus('Listening... no speech detected yet');
        return;
      }
      setTranscriptionError(`Speech error: ${event.error}`);
      shouldKeepListeningRef.current = false;
      setIsListening(false);
      setTranscriptionStatus('Listening stopped');
    };

    recognition.onend = () => {
      recognitionRef.current = null;
      if (shouldKeepListeningRef.current) {
        window.setTimeout(() => {
          if (shouldKeepListeningRef.current && !recognitionRef.current) {
            startListening();
          }
        }, 120);
        return;
      }
      setIsListening(false);
      setTranscriptionStatus('Listening ended');
    };

    recognition.start();
    recognitionRef.current = recognition;
    setIsListening(true);
    setTranscriptionError('');
    setTranscriptionStatus('Listening for speech...');
  }

  function stopListening() {
    shouldKeepListeningRef.current = false;
    if (transcriptInterimTimerRef.current) {
      window.clearTimeout(transcriptInterimTimerRef.current);
      transcriptInterimTimerRef.current = null;
    }
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setIsListening(false);
    setInterimText('');
    setTranscriptionStatus('Stopped');
  }

  function clearTranscript() {
    lastTranscriptCommittedRef.current = '';
    setTranscriptText('');
    setTranslatedTextByLanguage({});
    setInterimText('');
    setTranscriptionError('');
    setTranslationError('');
    setTranscriptionStatus('Ready');
  }

  async function startCamera() {
    try {
      if (cameraStreamRef.current) {
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      cameraStreamRef.current = stream;
      if (cameraVideoRef.current) {
        cameraVideoRef.current.srcObject = stream;
      }
      setCameraEnabled(true);
      setCameraError('');
      setCameraStatus('Camera ready');
    } catch (err) {
      setCameraError(err.message || 'Could not access camera.');
      setCameraStatus('Camera failed');
    }
  }

  function stopCamera() {
    void stopVlcStream();
    if (cameraStreamRef.current) {
      cameraStreamRef.current.getTracks().forEach((track) => track.stop());
      cameraStreamRef.current = null;
    }
    if (cameraVideoRef.current) {
      cameraVideoRef.current.srcObject = null;
    }
    setCameraEnabled(false);
  }

  function stopCameraListening() {
    shouldKeepCameraListeningRef.current = false;
    if (cameraInterimTimerRef.current) {
      window.clearTimeout(cameraInterimTimerRef.current);
      cameraInterimTimerRef.current = null;
    }
    cameraRecognitionRef.current?.stop();
    cameraRecognitionRef.current = null;
    setIsCameraListening(false);
    setCameraInterimText('');
    setCameraStatus('Subtitle listening stopped');
  }

  async function startVlcStream() {
    try {
      if (!cameraStreamRef.current) {
        await startCamera();
      }

      const relayResponse = await fetch(`${API_BASE}/vlc-stream/start`, { method: 'POST' });
      const relayPayload = await relayResponse.json().catch(() => ({}));
      if (!relayResponse.ok) {
        throw new Error(relayPayload.error || 'Could not start VLC relay.');
      }

      setVlcUrl(relayPayload.vlcUrl || 'udp://@127.0.0.1:1234');

      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${wsProtocol}//${window.location.host}/api/vlc-stream/ws`;
      const ws = new WebSocket(wsUrl);
      ws.binaryType = 'arraybuffer';

      ws.onopen = () => {
        const stream = cameraStreamRef.current;
        if (!stream) {
          setVlcError('Camera stream is not available for relay.');
          ws.close();
          return;
        }

        let recorder;
        try {
          recorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8,opus' });
        } catch (error) {
          recorder = new MediaRecorder(stream);
        }

        recorder.ondataavailable = async (event) => {
          if (!event.data || event.data.size === 0 || ws.readyState !== WebSocket.OPEN) {
            return;
          }
          const buffer = await event.data.arrayBuffer();
          ws.send(buffer);
        };

        recorder.onerror = () => {
          setVlcError('MediaRecorder error while sending stream to relay.');
        };

        recorder.start(500);
        vlcMediaRecorderRef.current = recorder;
        setIsVlcStreaming(true);
        setVlcStatus('Relay streaming. Open VLC Network Stream URL shown below.');
        setVlcError('');
      };

      ws.onmessage = (event) => {
        const message = String(event.data || '');
        if (message.startsWith('error:')) {
          setVlcError(message.replace('error:', '').trim());
        }
      };

      ws.onclose = () => {
        if (vlcMediaRecorderRef.current) {
          vlcMediaRecorderRef.current.stop();
          vlcMediaRecorderRef.current = null;
        }
        setIsVlcStreaming(false);
      };

      vlcWebSocketRef.current = ws;
    } catch (err) {
      setVlcError(err.message || 'Failed to start VLC streaming.');
      setVlcStatus('Relay failed');
      setIsVlcStreaming(false);
    }
  }

  async function stopVlcStream() {
    if (vlcMediaRecorderRef.current) {
      vlcMediaRecorderRef.current.stop();
      vlcMediaRecorderRef.current = null;
    }
    if (vlcWebSocketRef.current) {
      vlcWebSocketRef.current.close();
      vlcWebSocketRef.current = null;
    }

    try {
      await fetch(`${API_BASE}/vlc-stream/stop`, { method: 'POST' });
    } catch (err) {
      // Ignore best-effort stop failures.
    }

    setIsVlcStreaming(false);
    setVlcStatus('Relay stopped');
  }

  function startCameraListening() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setCameraError('Speech recognition is not available in this browser. Try Chrome or Edge.');
      return;
    }

    if (cameraRecognitionRef.current) {
      cameraRecognitionRef.current.stop();
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = cameraSourceLanguage;
    shouldKeepCameraListeningRef.current = true;

    recognition.onresult = (event) => {
      let interimSpeech = '';
      let finalSpeech = '';

      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const text = result[0].transcript.trim();

        if (result.isFinal) {
          finalSpeech += `${text} `;
        } else {
          interimSpeech += `${text} `;
        }
      }

      setCameraInterimText(interimSpeech.trim());
      if (interimSpeech.trim()) {
        if (cameraInterimTimerRef.current) {
          window.clearTimeout(cameraInterimTimerRef.current);
        }
        cameraInterimTimerRef.current = window.setTimeout(() => {
          commitCameraSubtitle(interimSpeech);
          cameraInterimTimerRef.current = null;
        }, pauseCommitMs);
      }

      if (finalSpeech.trim()) {
        if (cameraInterimTimerRef.current) {
          window.clearTimeout(cameraInterimTimerRef.current);
          cameraInterimTimerRef.current = null;
        }
        commitCameraSubtitle(finalSpeech);
      }
    };

    recognition.onerror = (event) => {
      if (event.error === 'no-speech') {
        setCameraStatus('Listening... no speech detected yet');
        return;
      }
      setCameraError(`Speech error: ${event.error}`);
      shouldKeepCameraListeningRef.current = false;
      setIsCameraListening(false);
      setCameraStatus('Subtitle listening failed');
    };

    recognition.onend = () => {
      cameraRecognitionRef.current = null;
      if (shouldKeepCameraListeningRef.current) {
        window.setTimeout(() => {
          if (shouldKeepCameraListeningRef.current && !cameraRecognitionRef.current) {
            startCameraListening();
          }
        }, 120);
        return;
      }
      setIsCameraListening(false);
      setCameraStatus('Subtitle listening ended');
    };

    recognition.start();
    cameraRecognitionRef.current = recognition;
    setIsCameraListening(true);
    setCameraError('');
    setCameraStatus('Listening for subtitle speech...');
  }

  useEffect(() => {
    if (!isVlcStreaming || !cameraSubtitle.trim()) {
      return;
    }

    const syncSubtitle = async () => {
      try {
        await fetch(`${API_BASE}/vlc-stream/subtitle`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: cameraSubtitle }),
        });
      } catch (error) {
        setVlcError('Could not sync subtitle text to VLC relay.');
      }
    };

    void syncSubtitle();
  }, [cameraSubtitle, isVlcStreaming]);

  useEffect(() => {
    lastCameraCommittedRef.current = '';
    setCameraInterimText('');
    setCameraSubtitle('');
  }, [cameraSourceLanguage, cameraTargetLanguage]);

  return (
    <div className="app-shell">
      <div className="main-area">
        <header className="top-bar">
          <div className="brand">PSSM</div>
          <nav className="nav-row">
            <button
              className={`nav-item ${activeView === 'download' ? 'active' : ''}`}
              type="button"
              onClick={() => setActiveView('download')}
            >
              Download Audio
            </button>
            <button
              className={`nav-item ${activeView === 'transcribe' ? 'active' : ''}`}
              type="button"
              onClick={() => setActiveView('transcribe')}
            >
              Live Transcribe
            </button>
            <button
              className={`nav-item ${activeView === 'cameraTranslate' ? 'active' : ''}`}
              type="button"
              onClick={() => setActiveView('cameraTranslate')}
            >
              Camera Subtitles
            </button>
          </nav>
        </header>

        <main className="content">
          {activeView === 'download' ? (
            <section className="panel">
              <h2>YouTube Audio Download</h2>
              <p>Download audio from a video ID using the existing Python workflow script.</p>

              <form onSubmit={handleStart} className="form-grid">
                <label htmlFor="videoId">Video ID or YouTube URL</label>
                <input
                  id="videoId"
                  value={videoInput}
                  onChange={(e) => setVideoInput(e.target.value)}
                  placeholder="e.g. Py8Z7D15JYo"
                />

                <label htmlFor="quality">Quality</label>
                <select id="quality" value={quality} onChange={(e) => setQuality(e.target.value)}>
                  {QUALITY_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>

                <button type="submit" disabled={!canSubmit}>
                  {isRunning ? 'Running...' : 'Download Audio'}
                </button>
              </form>

              <div className="progress-wrap" aria-live="polite">
                <div className="progress-label">Progress: {progress}%</div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${progress}%` }} />
                </div>
              </div>

              <div className="status-box">
                <strong>Info:</strong> {info}
              </div>

              {error ? (
                <div className="error-box">
                  <strong>Error:</strong> {error}
                </div>
              ) : null}

              <div className="log-box">
                {logs.length === 0 ? <div className="log-line muted">Logs will appear here.</div> : null}
                {logs.map((line, idx) => (
                  <div key={`${line}-${idx}`} className="log-line">
                    {line}
                  </div>
                ))}
              </div>
            </section>
          ) : activeView === 'transcribe' ? (
            <section className="panel">
              <h2>Live Voice Transcription</h2>
              <p>
                Click the microphone to capture speech live into the editor window. This uses the
                browser&apos;s speech recognition support for a fast local experience.
              </p>
              <p className="helper-text">
                Live transcription and translation are streamed as you speak. Translation uses Azure Translator when configured.
              </p>

              <div className="delay-control">
                <label htmlFor="pause-commit-ms" className="delay-control-label">
                  Pause before translate: {(pauseCommitMs / 1000).toFixed(1)}s
                </label>
                <input
                  id="pause-commit-ms"
                  className="delay-slider"
                  type="range"
                  min="300"
                  max="2500"
                  step="100"
                  value={pauseCommitMs}
                  onChange={(event) => setPauseCommitMs(Number(event.target.value))}
                />
                <div className="helper-text delay-hint">Lower values update faster. Higher values wait for a longer pause.</div>
              </div>

              <div className="toolbar-row">
                <div className="toolbar-actions">
                  <button
                    type="button"
                    className={`mic-button ${isListening ? 'listening' : ''}`}
                    onClick={isListening ? stopListening : startListening}
                  >
                    {isListening ? '⏹ Stop listening' : '🎤 Start listening'}
                  </button>
                  <button type="button" className="secondary-button" onClick={clearTranscript}>
                    Clear
                  </button>
                </div>
                <div className="language-buttons" role="group" aria-label="Select speaking language">
                  {languageOptions.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={`language-button ${selectedLanguage === option.value ? 'active' : ''}`}
                      onClick={() => setSelectedLanguage(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="transcription-layout">
                <div className="transcription-left">
                  <h3>Live transcript</h3>
                  <div className="status-box">
                    <strong>Status:</strong> {transcriptionStatus}
                  </div>

                  {transcriptionError ? (
                    <div className="error-box">
                      <strong>Error:</strong> {transcriptionError}
                    </div>
                  ) : null}

                  {interimText ? (
                    <div className="interim-box">
                      <strong>Live preview:</strong> {interimText}
                    </div>
                  ) : null}

                  <div className="translation-toolbar">
                    <span className="translation-label">Translate to</span>
                    <div className="language-buttons" role="group" aria-label="Select translation language">
                      {translationOptions.map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          className={`language-button ${selectedTranslationTargets.includes(option.value) ? 'active' : ''}`}
                          onClick={() => toggleTranslationTarget(option.value)}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {translationError ? (
                    <div className="error-box">
                      <strong>Translation:</strong> {translationError}
                    </div>
                  ) : null}

                  {selectedTranslationTargets.map((langCode) => {
                    const language = translationOptions.find((option) => option.value === langCode);
                    return (
                      <div key={langCode} className="translation-card">
                        <label htmlFor={`translation-output-${langCode}`} className="editor-label">
                          Live translation: {language?.label || langCode}
                        </label>
                        <textarea
                          id={`translation-output-${langCode}`}
                          className="editor-window translation-output"
                          value={translatedTextByLanguage[langCode] || ''}
                          readOnly
                          placeholder={`Translated text (${language?.label || langCode}) will appear here.`}
                        />
                      </div>
                    );
                  })}
                </div>

                <div className="transcription-right">
                  <textarea
                    id="transcript-editor"
                    className="editor-window"
                    value={transcriptText}
                    onChange={(event) => setTranscriptText(event.target.value)}
                    placeholder="Your live transcript will appear here. You can edit it as you go."
                  />
                </div>
              </div>
            </section>
          ) : (
            <section className="panel">
              <div className="camera-header">
                <div className="camera-header-left">
                  <h2>Live Camera Translation Subtitles</h2>
                  <p>Use camera preview with live translated subtitles over the video frame.</p>
                  <div className="delay-control delay-control-inline">
                    <label htmlFor="camera-pause-commit-ms" className="delay-control-label">
                      Pause before translate: {(pauseCommitMs / 1000).toFixed(1)}s
                    </label>
                    <input
                      id="camera-pause-commit-ms"
                      className="delay-slider"
                      type="range"
                      min="300"
                      max="2500"
                      step="100"
                      value={pauseCommitMs}
                      onChange={(event) => setPauseCommitMs(Number(event.target.value))}
                    />
                    <div className="helper-text delay-hint">Lower values update faster. Higher values wait for a longer pause.</div>
                  </div>
                </div>

                <div className="camera-header-right">
                  <div className="camera-toolbar">
                    <div className="toolbar-actions camera-actions">
                      <button type="button" className="mic-button" onClick={startCamera} disabled={cameraEnabled}>
                        Start Camera
                      </button>
                      <button type="button" className="secondary-button" onClick={stopCamera}>
                        Stop Camera
                      </button>
                      <button
                        type="button"
                        className={`mic-button ${isCameraListening ? 'listening' : ''}`}
                        onClick={isCameraListening ? stopCameraListening : startCameraListening}
                      >
                        {isCameraListening ? 'Stop Subtitle Listening' : 'Start Subtitle Listening'}
                      </button>
                      <button
                        type="button"
                        className={`mic-button ${isVlcStreaming ? 'listening' : ''}`}
                        onClick={isVlcStreaming ? stopVlcStream : startVlcStream}
                      >
                        {isVlcStreaming ? 'Stop VLC Relay' : 'Start VLC Relay'}
                      </button>
                    </div>
                    <div className="language-buttons" role="group" aria-label="Select subtitle source language">
                      {languageOptions.map((option) => (
                        <button
                          key={`cam-src-${option.value}`}
                          type="button"
                          className={`language-button ${cameraSourceLanguage === option.value ? 'active' : ''}`}
                          onClick={() => setCameraSourceLanguage(option.value)}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="translation-toolbar camera-translation-toolbar">
                    <span className="translation-label">Subtitle language</span>
                    <div className="language-buttons" role="group" aria-label="Select subtitle target language">
                      {translationOptions.map((option) => (
                        <button
                          key={`cam-tgt-${option.value}`}
                          type="button"
                          className={`language-button ${cameraTargetLanguage === option.value ? 'active' : ''}`}
                          onClick={() => setCameraTargetLanguage(option.value)}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              <div className="status-box">
                <strong>Status:</strong> {cameraStatus}
              </div>

              <div className="status-box">
                <strong>VLC Relay:</strong> {vlcStatus}
                <div className="vlc-url">Open in VLC: {vlcUrl}</div>
              </div>

              {cameraError ? (
                <div className="error-box">
                  <strong>Error:</strong> {cameraError}
                </div>
              ) : null}

              {vlcError ? (
                <div className="error-box">
                  <strong>VLC Error:</strong> {vlcError}
                </div>
              ) : null}

              {cameraInterimText ? (
                <div className="interim-box">
                  <strong>Heard:</strong> {cameraInterimText}
                </div>
              ) : null}

              <div className="camera-stage">
                <video ref={cameraVideoRef} className="camera-video" autoPlay muted playsInline />
                <div className="subtitle-overlay">{cameraSubtitle || 'Translated subtitles will appear here.'}</div>
              </div>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
