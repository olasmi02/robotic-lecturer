import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import { UploadCloud, FileText, Send, Sparkles, Loader2, Headphones, Play, Square, FileCheck, ClipboardList, Mic, X } from 'lucide-react';

const API_BASE = "https://robotic-lecturer.onrender.com";

// Safely initialize SpeechRecognition
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

function App() {
  const [documents, setDocuments] = useState([]);
  const [chatHistory, setChatHistory] = useState([]);
  const [inputValue, setInputValue] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  
  // Audio Overview State
  const [isGeneratingAudio, setIsGeneratingAudio] = useState(false);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [audioScript, setAudioScript] = useState([]);
  const [currentSpeakerLine, setCurrentSpeakerLine] = useState("");

  const messagesEndRef = useRef(null);
  const recognitionRef = useRef(null);
  const currentAudioRef = useRef(null); // Ref for HTMLAudioElement
  const currentLineIndexRef = useRef(0); // Ref to track which script line is currently playing

  useEffect(() => {
    // Setup Speech Recognition
    if (SpeechRecognition) {
      recognitionRef.current = new SpeechRecognition();
      recognitionRef.current.continuous = false;
      recognitionRef.current.interimResults = false;
      
      recognitionRef.current.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        setIsListening(false);
        handleAudioInterrupt(transcript);
      };
      
      recognitionRef.current.onerror = (event) => {
        console.error("Speech recognition error", event.error);
        setIsListening(false);
      };
      
      recognitionRef.current.onend = () => {
        setIsListening(false);
      };
    }
  }, []);

  const fetchDocuments = async () => {
    try {
      const res = await axios.get(`${API_BASE}/documents`);
      setDocuments(res.data);
    } catch (err) {
      console.error("Failed to fetch documents.", err);
    }
  };

  useEffect(() => {
    fetchDocuments();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, isTyping, currentSpeakerLine]);

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      await axios.post(`${API_BASE}/upload`, formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });
      fetchDocuments();
      setChatHistory(prev => [...prev, { role: 'ai', text: `I have successfully analyzed **${file.name}**. My cognitive engine is ready. \n\nWould you like me to generate a study guide, build a podcast, or test you with a quiz?` }]);
    } catch (err) {
      alert("Failed to upload document. Please ensure it's a valid file and backend is running.");
    } finally {
      setIsUploading(false);
      e.target.value = null;
    }
  };

  const handleDeleteDocument = async (docId) => {
    try {
      await axios.delete(`${API_BASE}/documents/${docId}`);
      fetchDocuments();
      setChatHistory(prev => [...prev, { role: 'ai', text: `I have removed that document from my memory bank.` }]);
    } catch (err) {
      alert("Failed to delete document.");
    }
  };

  const handleSendMessage = async (customQuery = null) => {
    const userMsg = customQuery || inputValue;
    if (!userMsg.trim()) return;
    
    if (!customQuery) setInputValue("");
    setChatHistory(prev => [...prev, { role: 'user', text: userMsg }]);
    setIsTyping(true);

    try {
      const res = await axios.post(`${API_BASE}/chat`, { query: userMsg });
      setChatHistory(prev => [...prev, {
        role: 'ai',
        text: res.data.response,
        citations: res.data.citations
      }]);
    } catch (err) {
      setChatHistory(prev => [...prev, {
        role: 'ai',
        text: "Sorry, I am currently experiencing connection issues to my cognitive engine. Please try again.",
        citations: []
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  // --- AUDIO LOGIC ---

  const handleGenerateAudioOverview = async () => {
    if (documents.length === 0) {
      alert("Please upload a document before generating a podcast audio overview!");
      return;
    }
    
    setIsGeneratingAudio(true);
    try {
      const res = await axios.post(`${API_BASE}/audio-overview`);
      const script = res.data.script;
      setAudioScript(script);
      playAudioScript(script);
    } catch (err) {
      alert("Failed to generate audio overview.");
    } finally {
      setIsGeneratingAudio(false);
    }
  };

  const playNextLine = (script, currentIndex) => {
    currentLineIndexRef.current = currentIndex;
    
    if (currentIndex >= script.length) {
      setIsPlayingAudio(false);
      setCurrentSpeakerLine("");
      return;
    }
    
    const line = script[currentIndex];
    setCurrentSpeakerLine(`${line.speaker}: "${line.text}"`);
    
    if (line.audio_data) {
      const audio = new Audio("data:audio/mp3;base64," + line.audio_data);
      audio.onended = () => playNextLine(script, currentIndex + 1);
      audio.play();
      currentAudioRef.current = audio;
    } else {
      // Fallback if audio generation failed for a line
      setTimeout(() => playNextLine(script, currentIndex + 1), 3000);
    }
  };

  const playAudioScript = (script) => {
    stopAudio();
    setIsPlayingAudio(true);
    playNextLine(script, 0);
  };

  const stopAudio = () => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current.currentTime = 0;
      currentAudioRef.current = null;
    }
    setIsPlayingAudio(false);
    setCurrentSpeakerLine("");
  };

  const toggleInterrupt = () => {
    if (!SpeechRecognition) {
      alert("Your browser does not support the Web Speech API. Please use Google Chrome or Microsoft Edge.");
      return;
    }

    stopAudio(); // Shuts up the current hosts
    setCurrentSpeakerLine("Listening to your question...");
    setIsListening(true);
    recognitionRef.current.start();
  };

  const handleAudioInterrupt = async (transcript) => {
    if (!transcript.trim()) return;
    
    // Save the remainder of the original script from exactly where it was interrupted
    const remainingScript = audioScript.slice(currentLineIndexRef.current + 1);
    
    // We do not pollute the main chat history with audio questions anymore! 
    // Just show it natively in the podcast player frame to mimic NotebookLM perfectly.
    setCurrentSpeakerLine(`You asked: "${transcript}" — Mark & Sarah are thinking...`);
    setIsGeneratingAudio(true);
    
    try {
      const res = await axios.post(`${API_BASE}/audio-interrupt`, { query: transcript });
      const newScript = res.data.script;
      
      // Combine the newly generated interruption sequence WITH the remainder of the original podcast
      const combinedScript = [...newScript, ...remainingScript];
      
      setAudioScript(combinedScript);
      playAudioScript(combinedScript); // Seamlessly play the answer, and then seamlessly resume!
    } catch (err) {
      alert("Podcast interrupted, but failed to process question.");
      setCurrentSpeakerLine("");
    } finally {
      setIsGeneratingAudio(false);
    }
  };

  return (
    <div className="app-container">
      {/* Sidebar */}
      <aside className="sidebar glass-panel">
        <div className="logo-area">
          <Sparkles className="logo-icon" size={28} />
          <span>RoboLecturer</span>
        </div>
        
        <label className={`upload-zone ${isUploading ? 'drag-active' : ''}`}>
          <input 
            type="file" 
            style={{ display: 'none' }} 
            onChange={handleFileUpload}
            accept=".pdf,.docx,.pptx"
            disabled={isUploading}
          />
          {isUploading ? (
            <Loader2 className="animate-spin" size={36} color="#a855f7" />
          ) : (
            <UploadCloud size={36} color="#a855f7" />
          )}
          <p>{isUploading ? "Ingesting knowledge..." : "Upload Syllabus (PDF, Word, PPTX)"}</p>
        </label>

        <div className="documents-list">
          <h4>Course Materials ({documents.length})</h4>
          {documents.length === 0 ? (
            <p style={{ fontSize: "0.875rem", color: "var(--text-muted)" }}>Drop some knowledge to get started.</p>
          ) : (
            documents.map((doc, idx) => (
              <div key={idx} className="document-item" style={{display: 'flex', alignItems: 'center', gap: '0.5rem', justifyContent: 'space-between'}}>
                <div style={{display: 'flex', alignItems: 'center', gap: '0.5rem', overflow: 'hidden'}}>
                  <FileText size={16} color="#8b5cf6" style={{flexShrink: 0}} />
                  <span className="doc-name" title={doc.filename} style={{whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>
                    {doc.filename}
                  </span>
                </div>
                <button 
                  onClick={() => handleDeleteDocument(doc.id)} 
                  style={{background: 'none', border: 'none', color: '#ef4444', cursor: 'pointer', padding: '2px', display: 'flex', alignItems: 'center'}}
                  title="Remove Document"
                >
                  <X size={14} />
                </button>
              </div>
            ))
          )}
        </div>
      </aside>

      {/* Main Chat Area */}
      <main className="main-chat-area glass-panel">
        
        {/* Audio Overview Player Widget */}
        {(isGeneratingAudio || isPlayingAudio || audioScript.length > 0 || isListening) && (
          <div className="audio-player-widget">
            <div className="audio-header">
              <Headphones size={20} color="#a855f7" />
              <span>Podcast Overview: Mark & Sarah</span>
            </div>
            
            {isGeneratingAudio ? (
              <div className="audio-status"><Loader2 className="animate-spin" size={16} /> Generating Neural Voices...</div>
            ) : isListening ? (
              <div className="audio-status" style={{color: '#ef4444'}}>
                <Loader2 className="animate-spin" size={16} /> Recording microphone... Speak now!
              </div>
            ) : isPlayingAudio ? (
              <div className="audio-content">
                <p className="active-speaker">{currentSpeakerLine}</p>
                <div style={{display: 'flex', gap: '0.5rem'}}>
                  <button className="ctrl-btn interrupt-btn" onClick={toggleInterrupt}>
                    <Mic size={16} /> Interrupt
                  </button>
                  <button className="ctrl-btn stop-btn" onClick={stopAudio}>
                    <Square size={16} /> Stop
                  </button>
                </div>
              </div>
            ) : (
              <div className="audio-content">
                <p className="active-speaker">{currentSpeakerLine || "Podcast ready!"}</p>
                <div style={{display: 'flex', gap: '0.5rem'}}>
                  <button className="ctrl-btn play-btn" onClick={() => playAudioScript(audioScript)}>
                    <Play size={16} /> Play
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        <div className="chat-history">
          {chatHistory.length === 0 && (
            <div className="empty-state">
              <Sparkles size={56} color="#8b5cf6" style={{margin: "0 auto 1.5rem auto", opacity: 0.8}} />
              <h2>Welcome to Class</h2>
              <p>Chat with me normally, or upload a document to begin NotebookLM styled contextual analysis.</p>
            </div>
          )}

          {chatHistory.map((msg, idx) => (
            <div key={idx} className={`message-bubble ${msg.role === 'user' ? 'message-user' : 'message-ai'}`}>
              {msg.role === 'user' ? (
                <p>{msg.text}</p>
              ) : (
                <>
                  <ReactMarkdown>{msg.text}</ReactMarkdown>
                  {msg.citations && msg.citations.length > 0 && (
                    <div className="citations-container">
                      <p style={{ fontSize: "0.75rem", fontWeight: "600", color: "#a855f7", marginBottom: "0.5rem", textTransform: "uppercase" }}>
                        Sources
                      </p>
                      {msg.citations.map((cite) => (
                        <div key={cite.id} className="citation-source">
                          <strong>{cite.source}</strong>
                          "{cite.snippet}"
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
          
          {isTyping && (
            <div className="message-bubble message-ai" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', opacity: 0.8 }}>
              <Loader2 className="animate-spin" size={20} color="#a855f7" /> 
              <span>Synthesizing response...</span>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Suggestion Chips */}
        <div className="suggestion-chips">
          <button className="chip" onClick={() => handleSendMessage("Can you give me a comprehensive Study Guide summarizing all the uploaded material?")}>
            <ClipboardList size={14} /> Study Guide
          </button>
          <button className="chip" onClick={() => handleSendMessage("Can you act as my teacher and quiz me on the core concepts of this material? Ask me a question, wait for my answer, and then score me.")}>
             <FileCheck size={14} /> Quiz Me
          </button>
          <button className="chip highlight-chip" onClick={handleGenerateAudioOverview} disabled={isGeneratingAudio || isUploading || documents.length === 0}>
             <Headphones size={14} /> Generate Podcast
          </button>
        </div>

        <div className="input-area">
          <div className="input-container">
            <input 
              className="input-field"
              placeholder="Ask a question or type a response..."
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
              disabled={isTyping || isUploading || isListening}
            />
            <button className="send-button" onClick={() => handleSendMessage()} disabled={isTyping || isUploading || !inputValue.trim() || isListening}>
              <Send size={18} />
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
