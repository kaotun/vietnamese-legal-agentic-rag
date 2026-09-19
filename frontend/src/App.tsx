import React, { useState, useEffect, useRef } from 'react';
import { marked } from 'marked';

marked.setOptions({
  breaks: true,
  gfm: true,
});

function MarkdownContent({ content }: { content: string }) {
  const html = marked.parse(content || '') as string;
  return (
    <div
      className="markdown-body text-sm sm:text-base leading-relaxed text-on-surface"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function Icon({ name, className = '' }: { name: string; className?: string }) {
  return (
    <span className={`material-symbols-outlined ${className}`} style={{ fontFamily: 'Material Symbols Outlined' }}>
      {name}
    </span>
  );
}

interface RetrievedDoc {
  id?: number | string;
  law_id?: string;
  law_name?: string;
  doc_type?: string;
  article?: string;
  article_title?: string;
  content?: string;
  text?: string;
  focused_content?: string;
  citation?: string;
  article_number?: string;
  score?: number;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: string;
  intent?: string;
  citations?: string[];
  standalone_query?: string;
  retrieved_docs?: RetrievedDoc[];
  guard_status?: string;
  followup_questions?: string[];
}

interface SessionItem {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  turn_count: number;
  last_snippet?: string;
}

const DEFAULT_FOLLOWUP_QUESTIONS = [
  'Mức phạt xe máy và ô tô vượt đèn đỏ khác nhau thế nào?',
  'Thời gian thử việc tối đa theo Bộ luật Lao động 2019?',
  'Điều kiện để người lao động được hưởng trợ cấp thất nghiệp?',
];

const LAW_CHIPS = [
  { label: 'Giao thông', prompt: 'Mức phạt xe máy vượt đèn đỏ theo quy định hiện hành?' },
  { label: 'Lao động', prompt: 'Thời gian thử việc tối đa là bao lâu theo Bộ luật Lao động?' },
  { label: 'BHXH', prompt: 'Điều kiện hưởng chế độ thai sản khi sinh con?' },
  { label: 'Đất đai', prompt: 'Căn cứ bồi thường khi nhà nước thu hồi đất ở?' },
  { label: 'Dân sự', prompt: 'Quy định về thời hiệu khởi kiện tranh chấp hợp đồng dân sự?' },
  { label: 'Hình sự', prompt: 'Các tình tiết giảm nhẹ trách nhiệm hình sự theo Bộ luật Hình sự?' },
];

const RAG_PIPELINE_STAGES = [
  {
    step: 1,
    totalSteps: 4,
    shortName: 'Phân tích ý định',
    title: 'Phân tích câu hỏi & Xác định ý định pháp lý',
    description: 'Bóc tách từ khóa, chuẩn hóa ngữ cảnh và định tuyến ý định câu hỏi',
    icon: 'psychology',
  },
  {
    step: 2,
    totalSteps: 4,
    shortName: 'Truy hồi VBPL',
    title: 'Truy vấn CSDL Quốc gia VBPL (Hybrid RAG)',
    description: 'Tìm kiếm đa tầng BM25 kết hợp Vector Dense & mở rộng truy vấn HyDE',
    icon: 'travel_explore',
  },
  {
    step: 3,
    totalSteps: 4,
    shortName: 'Kiểm định đối chiếu',
    title: 'Tái xếp hạng & Kiểm định điều luật đối chiếu',
    description: 'BGE-Reranker chấm điểm tương đồng và xác thực số hiệu Điều, Khoản',
    icon: 'fact_check',
  },
  {
    step: 4,
    totalSteps: 4,
    shortName: 'Biên soạn tư vấn',
    title: 'Tổng hợp căn cứ & Biên soạn văn bản tư vấn',
    description: 'Mô hình AI tổng hợp luận điểm và chuẩn hóa cấu trúc tư vấn 4 phần',
    icon: 'edit_note',
  },
];



export default function App() {
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = localStorage.getItem('legal_ai_theme');
    if (saved === 'dark' || saved === 'light') return saved;
    return typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light';
  });

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
    localStorage.setItem('legal_ai_theme', theme);
  }, [theme]);

  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>('default');
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content:
        'Xin chào bạn! Tôi là **Trợ lý Pháp luật Việt Nam** được kết nối với CSDL Văn bản Quy phạm Pháp luật Quốc gia. Bạn có thể đặt câu hỏi về luật Giao thông, Lao động, Bảo hiểm, Đất đai hoặc hỏi trực tiếp qua microphone!',
      timestamp: 'Vừa xong',
      intent: 'smalltalk',
    },
  ]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [disclaimerVisible, setDisclaimerVisible] = useState(true);
  const [ragExpanded, setRagExpanded] = useState(true);
  const [inspectorVisible, setInspectorVisible] = useState(true);
  const [sidebarVisible, setSidebarVisible] = useState<boolean>(() => {
    const saved = localStorage.getItem('legal_ai_sidebar');
    if (saved === 'false') return false;
    return true;
  });

  useEffect(() => {
    localStorage.setItem('legal_ai_sidebar', String(sidebarVisible));
  }, [sidebarVisible]);
  const [selectedDoc, setSelectedDoc] = useState<RetrievedDoc | null>(null);
  const [activeDocList, setActiveDocList] = useState<RetrievedDoc[]>([]);
  const [copiedDoc, setCopiedDoc] = useState(false);
  const [contentViewMode, setContentViewMode] = useState<'full' | 'focused'>('full');
  const [isListening, setIsListening] = useState(false);
  const [playingIndex, setPlayingIndex] = useState<number | null>(null);
  const [followupQuestions, setFollowupQuestions] = useState<string[]>(DEFAULT_FOLLOWUP_QUESTIONS);
  const [sessionToDelete, setSessionToDelete] = useState<string | null>(null);
  const [isDeletingSession, setIsDeletingSession] = useState(false);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState<string>('');

  // Tiến trình đa tầng của quy trình hỏi đáp RAG
  const [progressStageIndex, setProgressStageIndex] = useState(0);
  const [progressPercent, setProgressPercent] = useState(15);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const progressTimerRef = useRef<any>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const recognitionRef = useRef<any>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  // Quản lý kéo lướt ngang & cuộn danh sách tab điều luật
  const tabsContainerRef = useRef<HTMLDivElement | null>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const isDraggingTabsRef = useRef(false);
  const tabsStartXRef = useRef(0);
  const tabsScrollLeftRef = useRef(0);
  const tabsHasMovedRef = useRef(false);

  const checkTabsScroll = () => {
    const el = tabsContainerRef.current;
    if (!el) return;
    setCanScrollLeft(el.scrollLeft > 2);
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 2);
  };

  const scrollTabs = (offset: number) => {
    tabsContainerRef.current?.scrollBy({ left: offset, behavior: 'smooth' });
    setTimeout(checkTabsScroll, 300);
  };

  const handleTabsMouseDown = (e: React.MouseEvent) => {
    const el = tabsContainerRef.current;
    if (!el) return;
    isDraggingTabsRef.current = true;
    tabsHasMovedRef.current = false;
    tabsStartXRef.current = e.pageX - el.offsetLeft;
    tabsScrollLeftRef.current = el.scrollLeft;
  };

  const handleTabsMouseMove = (e: React.MouseEvent) => {
    if (!isDraggingTabsRef.current) return;
    const el = tabsContainerRef.current;
    if (!el) return;
    const x = e.pageX - el.offsetLeft;
    const walk = (x - tabsStartXRef.current) * 1.5;
    if (Math.abs(walk) > 4) {
      tabsHasMovedRef.current = true;
    }
    el.scrollLeft = tabsScrollLeftRef.current - walk;
    checkTabsScroll();
  };

  const handleTabsMouseUp = () => {
    isDraggingTabsRef.current = false;
  };

  const handleTabsWheel = (e: React.WheelEvent) => {
    const el = tabsContainerRef.current;
    if (!el) return;
    if (e.deltaY !== 0) {
      el.scrollLeft += e.deltaY;
      checkTabsScroll();
    }
  };

  // Tải danh sách phiên hội thoại khi vào trang
  useEffect(() => {
    fetchSessions();
  }, []);

  // Tự động cuộn xuống cuối khung chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming]);

  // Tự động truy xuất toàn văn từ CSDL nếu tài liệu đang chọn chỉ là nhãn trích lục
  useEffect(() => {
    if (!selectedDoc) return;
    const content = selectedDoc.content || selectedDoc.text || '';
    const isPlaceholder =
      !content ||
      content.startsWith('Trích lục điều luật:') ||
      content.includes('Nội dung điều luật trích dẫn trong văn bản.');
    if (isPlaceholder) {
      const citeQuery = selectedDoc.citation || selectedDoc.article_number || selectedDoc.article;
      if (citeQuery) {
        fetch(`/api/articles/lookup?citation=${encodeURIComponent(citeQuery)}`)
          .then((res) => (res.ok ? res.json() : null))
          .then((doc) => {
            if (doc && doc.content) {
              setSelectedDoc(doc);
              setActiveDocList((prev) => {
                if (!prev.some((d) => d.article === doc.article)) {
                  return [...prev, doc];
                }
                return prev.map((d) => (d.article === doc.article ? doc : d));
              });
            }
          })
          .catch((err) => console.warn('Lỗi tự động tra cứu điều luật:', err));
      }
    }
  }, [selectedDoc?.article_number, selectedDoc?.article, selectedDoc?.citation]);

  // Tự động kiểm tra và căn giữa tab điều luật đang chọn
  useEffect(() => {
    checkTabsScroll();
    const el = tabsContainerRef.current;
    if (!el || !selectedDoc) return;
    const timer = setTimeout(() => {
      checkTabsScroll();
      const activeBtn = el.querySelector('[data-selected="true"]') as HTMLElement;
      if (activeBtn) {
        activeBtn.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
      }
    }, 60);
    return () => clearTimeout(timer);
  }, [selectedDoc, activeDocList]);

  // Điều khiển thanh tiến trình đa tầng có ý nghĩa và sinh động theo thời gian thực
  useEffect(() => {
    if (isStreaming) {
      setProgressPercent(15);
      setProgressStageIndex(0);
      setElapsedSeconds(0);
      const startTime = Date.now();

      progressTimerRef.current = setInterval(() => {
        const elapsed = (Date.now() - startTime) / 1000;
        setElapsedSeconds(elapsed);

        if (elapsed < 0.8) {
          setProgressStageIndex(0);
          setProgressPercent(Math.min(28, 15 + (elapsed / 0.8) * 13));
        } else if (elapsed < 2.0) {
          setProgressStageIndex(1);
          setProgressPercent(Math.min(58, 28 + ((elapsed - 0.8) / 1.2) * 30));
        } else if (elapsed < 3.5) {
          setProgressStageIndex(2);
          setProgressPercent(Math.min(82, 58 + ((elapsed - 2.0) / 1.5) * 24));
        } else {
          setProgressStageIndex(3);
          const extra = Math.min(14, (elapsed - 3.5) * 1.6);
          setProgressPercent(Math.min(96, 82 + extra));
        }
      }, 80);
    } else {
      if (progressTimerRef.current) {
        clearInterval(progressTimerRef.current);
        progressTimerRef.current = null;
      }
    }

    return () => {
      if (progressTimerRef.current) {
        clearInterval(progressTimerRef.current);
      }
    };
  }, [isStreaming]);

  const fetchSessions = async () => {
    try {
      const res = await fetch('/api/sessions');
      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions || []);
      }
    } catch (err) {
      console.warn('Chưa kết nối được API sessions backend:', err);
    }
  };

  const handleSelectSession = async (sessionId: string) => {
    setCurrentSessionId(sessionId);
    try {
      const res = await fetch(`/api/sessions/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        const loadedMsgs: Message[] = (data.messages || []).map((m: any) => ({
          role: m.role,
          content: m.content,
          timestamp: m.timestamp ? new Date(m.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '',
          intent: m.intent,
          citations: m.citations || [],
          standalone_query: m.standalone_query,
          retrieved_docs: m.retrieved_docs || [],
          followup_questions: m.followup_questions || [],
        }));
        setMessages(loadedMsgs);
        if (loadedMsgs.length > 0) {
          const lastAssistant = [...loadedMsgs].reverse().find((m) => m.role === 'assistant');
          if (lastAssistant?.followup_questions && lastAssistant.followup_questions.length > 0) {
            setFollowupQuestions(lastAssistant.followup_questions);
          } else {
            setFollowupQuestions(DEFAULT_FOLLOWUP_QUESTIONS);
          }
          if (lastAssistant?.retrieved_docs && lastAssistant.retrieved_docs.length > 0) {
            setSelectedDoc(lastAssistant.retrieved_docs[0]);
            setActiveDocList(lastAssistant.retrieved_docs);
          } else if (lastAssistant?.citations && lastAssistant.citations.length > 0) {
            const firstCite = lastAssistant.citations[0];
            setSelectedDoc({
              article: firstCite.split('(')[0].trim(),
              article_number: firstCite,
              citation: firstCite,
              law_name: 'Đang tải CSDL VBPL...',
              text: 'Đang kết nối CSDL và truy xuất toàn văn điều luật...',
              content: 'Đang kết nối CSDL và truy xuất toàn văn điều luật...',
            });
            fetch(`/api/articles/lookup?citation=${encodeURIComponent(firstCite)}`)
              .then((res) => (res.ok ? res.json() : null))
              .then((doc) => {
                if (doc && doc.content) {
                  setSelectedDoc(doc);
                  setActiveDocList([doc]);
                }
              })
              .catch(() => {});
          }
        }
      }
    } catch (err) {
      console.error('Lỗi khi nạp session:', err);
    }
  };

  const handleCreateNewSession = async () => {
    try {
      const res = await fetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'Cuộc hội thoại mới' }),
      });
      if (res.ok) {
        const data = await res.json();
        const newSess = data.session;
        setSessions((prev) => [newSess, ...prev]);
        setCurrentSessionId(newSess.id);
        setMessages([
          {
            role: 'assistant',
            content: 'Đã tạo cuộc hội thoại mới! Bạn cần hỗ trợ tra cứu quy định pháp luật nào hôm nay?',
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            intent: 'smalltalk',
          },
        ]);
        setFollowupQuestions(DEFAULT_FOLLOWUP_QUESTIONS);
        setSelectedDoc(null);
      }
    } catch (err) {
      console.error('Lỗi tạo session mới:', err);
    }
  };

  const handleDeleteSession = (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    setSessionToDelete(sessionId);
  };

  const confirmDeleteSession = async () => {
    if (!sessionToDelete) return;
    setIsDeletingSession(true);
    try {
      const res = await fetch(`/api/sessions/${sessionToDelete}`, { method: 'DELETE' });
      if (res.ok) {
        const remaining = sessions.filter((s) => s.id !== sessionToDelete);
        setSessions(remaining);
        if (currentSessionId === sessionToDelete) {
          if (remaining.length > 0) {
            // Mặc định quay lại đoạn hội thoại đầu tiên
            await handleSelectSession(remaining[0].id);
          } else {
            // Nếu đã xóa hết tất cả các đoạn hội thoại, khởi tạo cuộc trò chuyện mới
            await handleCreateNewSession();
          }
        }
      }
    } catch (err) {
      console.error('Lỗi xóa session:', err);
    } finally {
      setIsDeletingSession(false);
      setSessionToDelete(null);
    }
  };

  const handleStartRename = (e: React.MouseEvent, session: SessionItem) => {
    e.stopPropagation();
    setEditingSessionId(session.id);
    setEditingTitle(session.title);
  };

  const handleSaveRename = async (sessionId: string) => {
    const trimmed = editingTitle.trim();
    if (!trimmed) {
      setEditingSessionId(null);
      return;
    }
    try {
      const res = await fetch(`/api/sessions/${sessionId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: trimmed }),
      });
      if (res.ok) {
        setSessions((prev) =>
          prev.map((s) => (s.id === sessionId ? { ...s, title: trimmed } : s))
        );
      }
    } catch (err) {
      console.error('Lỗi khi đổi tên session:', err);
    } finally {
      setEditingSessionId(null);
    }
  };

  const handleSend = async (queryText?: string) => {
    const q = (queryText || input).trim();
    if (!q || isStreaming) return;
    setInput('');

    const userMsg: Message = {
      role: 'user',
      content: q,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: q,
          session_id: currentSessionId,
        }),
      });

      if (!res.ok) throw new Error('Không thể nhận phản hồi từ API backend');
      const data = await res.json();

      // Nhảy vọt lên 100% khi nhận kết quả thành công và nán lại một thoáng mượt mà
      setProgressPercent(100);
      setProgressStageIndex(3);
      await new Promise((resolve) => setTimeout(resolve, 220));

      const assistantMsg: Message = {
        role: 'assistant',
        content: data.answer,
        intent: data.intent,
        citations: data.citations || [],
        standalone_query: data.standalone_query,
        retrieved_docs: data.retrieved_docs || [],
        guard_status: data.guard_status || 'passed',
        followup_questions: data.followup_questions || [],
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };

      setMessages((prev) => [...prev, assistantMsg]);

      // Cập nhật các câu hỏi gợi ý đào sâu động theo ngữ cảnh
      if (data.followup_questions && data.followup_questions.length > 0) {
        setFollowupQuestions(data.followup_questions);
      }

      // Nếu có tài liệu trích dẫn, tự động chọn tài liệu đầu tiên cho Inspector bên phải
      if (data.retrieved_docs && data.retrieved_docs.length > 0) {
        setSelectedDoc(data.retrieved_docs[0]);
        setActiveDocList(data.retrieved_docs);
      } else if (data.citations && data.citations.length > 0) {
        setSelectedDoc({
          article_number: data.citations[0],
          law_name: 'Văn bản quy phạm pháp luật trích dẫn',
          content: data.answer,
          text: data.answer,
        });
        setActiveDocList([]);
      }

      // Cập nhật lại danh sách sessions trên sidebar
      fetchSessions();
    } catch (err: any) {
      console.error(err);
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: 'Xin lỗi, không thể kết nối tới máy chủ backend. Vui lòng đảm bảo FastAPI backend đang chạy tại port 8000.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    } finally {
      setIsStreaming(false);
    }
  };

  // Tính năng nhận diện giọng nói (STT)
  const toggleSpeechRecognition = () => {
    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
      return;
    }

    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert('Trình duyệt của bạn chưa hỗ trợ Web Speech API. Vui lòng dùng Chrome, Edge hoặc Safari!');
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = 'vi-VN';
    recognition.continuous = false;
    recognition.interimResults = true;

    recognition.onstart = () => setIsListening(true);
    recognition.onresult = (e: any) => {
      const transcript = Array.from(e.results)
        .map((r: any) => r[0].transcript)
        .join('');
      setInput(transcript);
    };
    recognition.onerror = () => setIsListening(false);
    recognition.onend = () => setIsListening(false);

    recognitionRef.current = recognition;
    recognition.start();
  };

  // Tính năng đọc câu trả lời bằng giọng nói (TTS) tối ưu tốc độ & không độ trễ
  const handlePlayTTS = async (text: string, msgIdx: number) => {
    // Nếu đang phát chính tin nhắn này thì dừng lại
    if (playingIndex === msgIdx) {
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel();
      }
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      setPlayingIndex(null);
      return;
    }

    // Dừng mọi âm thanh đang phát trước đó
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }

    // Làm sạch văn bản: loại bỏ Markdown và danh mục gợi ý câu hỏi ở cuối
    let cleanText = text.split(/\[GỢI Ý CÂU HỎI TIẾP THEO\]/i)[0];
    cleanText = cleanText
      .replace(/#+/g, '')
      .replace(/[*_]{1,3}(.*?)[*_]{1,3}/g, '$1')
      .replace(/\[(.*?)\]\(.*?\)/g, '$1')
      .replace(/^[\s\-*+]+|[0-9]+\.\s+/gm, '. ')
      .replace(/\n+/g, '. ')
      .replace(/\s+/g, ' ')
      .replace(/\.+/g, '.')
      .replace(/^[\s\.\,\;\:\?\!\-]+/, '')
      .trim();

    // 1. Ưu tiên phát ngay lập tức qua Web Speech API nội bộ trình duyệt (0s độ trễ mạng)
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try {
        setPlayingIndex(msgIdx);
        const utterance = new SpeechSynthesisUtterance(cleanText);
        utterance.lang = 'vi-VN';
        utterance.rate = 1.15; // Tăng tốc 15% giúp giọng đọc nhanh, dứt khoát và tiết kiệm thời gian

        const voices = window.speechSynthesis.getVoices();
        const viVoice = voices.find((v) => v.lang.toLowerCase().includes('vi'));
        if (viVoice) {
          utterance.voice = viVoice;
        }

        utterance.onend = () => setPlayingIndex(null);
        utterance.onerror = () => setPlayingIndex(null);

        window.speechSynthesis.speak(utterance);
        return;
      } catch (e) {
        console.warn('Lỗi Web Speech API, chuyển sang Backend Edge-TTS:', e);
      }
    }

    // 2. Fallback sang Edge-TTS backend nếu thiết bị không hỗ trợ Web Speech
    try {
      setPlayingIndex(msgIdx);
      const res = await fetch('/api/voice/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: cleanText, voice: 'vi-VN-HoaiMyNeural', rate: '+15%' }),
      });
      if (!res.ok) throw new Error('Không thể tải file âm thanh');

      const blob = await res.blob();
      const audioUrl = URL.createObjectURL(blob);

      const audio = new Audio(audioUrl);
      audioRef.current = audio;
      audio.onended = () => setPlayingIndex(null);
      audio.onerror = () => setPlayingIndex(null);
      audio.play();
    } catch (err) {
      console.error('Lỗi TTS:', err);
      setPlayingIndex(null);
    }
  };

  return (
    <div className="bg-surface font-body text-on-surface antialiased min-h-screen" style={{ fontFamily: 'Public Sans, sans-serif' }}>
      {/* Header */}
      <header className="fixed top-0 left-0 right-0 z-50 bg-surface/90 backdrop-blur-xl shadow-[0_1px_8px_rgba(0,0,0,0.04)]">
        <div className="h-16 w-full px-6 flex items-center justify-between">
          <div className="flex items-center">
            <button
              type="button"
              onClick={() => setSidebarVisible(!sidebarVisible)}
              className="group flex items-center gap-3 rounded-2xl p-1 -ml-1 hover:bg-surface-container/60 transition-all cursor-pointer focus:outline-none"
              title={sidebarVisible ? 'Thu gọn thanh bên' : 'Mở rộng thanh bên'}
              aria-label={sidebarVisible ? 'Thu gọn thanh bên' : 'Mở rộng thanh bên'}
            >
              {/* Logo Box with Hover Icon Swap */}
              <div className="relative w-10 h-10 rounded-2xl bg-gradient-to-tr from-primary to-primary-container p-0.5 shadow-md flex items-center justify-center transition-transform group-hover:scale-105">
                <div className="w-full h-full bg-surface-container-lowest rounded-[14px] flex items-center justify-center overflow-hidden relative">
                  {/* Normal Gavel Icon */}
                  <Icon
                    name="gavel"
                    className="text-primary text-[22px] transition-all duration-200 group-hover:opacity-0 group-hover:scale-75"
                  />
                  {/* Hover Icon (Expand when closed, Collapse when open) */}
                  <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all duration-200 bg-primary/10">
                    <Icon
                      name="dock_to_left"
                      className="text-primary text-[20px] transition-transform duration-200 group-hover:scale-110"
                    />
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-base font-bold tracking-tight text-on-surface group-hover:text-primary transition-colors">
                  Legal AI
                </span>
              </div>
            </button>
          </div>
          <div className="flex items-center gap-3">
            <button
              aria-label="Toggle Inspector"
              onClick={() => setInspectorVisible(!inspectorVisible)}
              className="px-3 py-1.5 rounded-xl bg-surface-container hover:bg-surface-container-high text-xs font-medium flex items-center gap-1.5 transition-colors text-on-surface"
            >
              <Icon name="menu_book" className="text-[16px] text-primary" />
              <span className="hidden sm:inline">{inspectorVisible ? 'Thu gọn Nguồn VBPL' : 'Xem Nguồn VBPL'}</span>
            </button>
          </div>
        </div>
      </header>

      {/* Sidebar */}
      <aside
        className={`fixed left-0 top-16 bottom-0 w-72 bg-surface-container-low z-40 flex flex-col justify-between overflow-y-auto shadow-[0_1px_8px_rgba(0,0,0,0.03)] transition-transform duration-300 ease-in-out ${
          sidebarVisible ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="p-4 flex flex-col gap-4">
          <button
            onClick={handleCreateNewSession}
            className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl bg-primary text-on-primary font-medium text-sm shadow-[0_1px_8px_rgba(0,0,0,0.06)] hover:bg-primary-container hover:text-on-primary-container transition-all"
          >
            <Icon name="add" className="text-[20px]" />
            <span>Hội thoại mới</span>
          </button>



          <div>
            <div className="px-2 mb-2 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">Lĩnh vực luật nhanh</div>
            <div className="flex flex-wrap gap-1.5 px-1">
              {LAW_CHIPS.map((chip) => (
                <button
                  key={chip.label}
                  onClick={() => handleSend(chip.prompt)}
                  className="px-2.5 py-1 text-xs rounded-lg bg-surface-container text-on-surface-variant hover:bg-secondary-container hover:text-on-secondary-container transition-colors"
                  type="button"
                >
                  {chip.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between px-2 mb-2 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
              <span>Lịch sử hội thoại ({sessions.length})</span>
            </div>
            <div className="flex flex-col gap-1 max-h-[calc(100vh-340px)] overflow-y-auto pr-1">
              {sessions.length === 0 ? (
                <p className="text-[11px] text-on-surface-variant px-2 italic">Chưa có lịch sử hội thoại cũ</p>
              ) : (
                sessions.map((item) => (
                  editingSessionId === item.id ? (
                    <div
                      key={item.id}
                      onClick={(e) => e.stopPropagation()}
                      className="p-1.5 rounded-xl bg-primary/10 border border-primary flex items-center gap-1.5"
                    >
                      <input
                        type="text"
                        value={editingTitle}
                        onChange={(e) => setEditingTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleSaveRename(item.id);
                          if (e.key === 'Escape') setEditingSessionId(null);
                        }}
                        autoFocus
                        className="flex-1 bg-surface-container text-xs text-on-surface px-2 py-1 rounded-lg border border-outline/40 focus:outline-none focus:ring-1 focus:ring-primary min-w-0"
                      />
                      <button
                        onClick={() => handleSaveRename(item.id)}
                        className="p-1 text-primary hover:text-primary-dark transition-colors flex-shrink-0"
                        title="Lưu tên mới (Enter)"
                      >
                        <Icon name="check" className="text-[16px]" />
                      </button>
                      <button
                        onClick={() => setEditingSessionId(null)}
                        className="p-1 text-on-surface-variant hover:text-error transition-colors flex-shrink-0"
                        title="Hủy (Esc)"
                      >
                        <Icon name="close" className="text-[16px]" />
                      </button>
                    </div>
                  ) : (
                    <div
                      key={item.id}
                      onClick={() => handleSelectSession(item.id)}
                      className={`group p-2 rounded-xl transition-all cursor-pointer flex items-center justify-between ${
                        currentSessionId === item.id ? 'bg-primary/10 border-l-2 border-primary' : 'bg-surface-container/60 hover:bg-surface-container-high'
                      }`}
                    >
                      <div className="flex items-center gap-2 text-xs font-medium text-on-surface truncate pr-1 min-w-0">
                        <Icon name="chat_bubble_outline" className="text-[16px] text-primary flex-shrink-0" />
                        <span className="truncate">{item.title}</span>
                      </div>
                      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                        <button
                          onClick={(e) => handleStartRename(e, item)}
                          className="p-1 text-on-surface-variant hover:text-primary transition-colors"
                          title="Đổi tên đoạn chat này"
                        >
                          <Icon name="edit" className="text-[15px]" />
                        </button>
                        <button
                          onClick={(e) => handleDeleteSession(e, item.id)}
                          className="p-1 text-on-surface-variant hover:text-error transition-colors"
                          title="Xóa đoạn chat này"
                        >
                          <Icon name="delete" className="text-[15px]" />
                        </button>
                      </div>
                    </div>
                  )
                ))
              )}
            </div>
          </div>
        </div>

        {/* Sidebar Footer */}
        <div className="p-4 bg-surface-container mt-4 border-t border-outline-variant/30">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-8 h-8 rounded-full bg-secondary-container text-on-secondary-container flex items-center justify-center flex-shrink-0">
                <Icon name="person" className="text-[18px]" />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold text-on-surface truncate">Người dùng</p>
                <p className="text-[10px] text-on-surface-variant truncate">Phiên làm việc</p>
              </div>
            </div>
            <button
              aria-label="Toggle Theme"
              onClick={() => setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'))}
              className="p-1.5 rounded-lg text-on-surface-variant hover:text-primary hover:bg-surface-container-high transition-colors flex items-center justify-center"
              title={theme === 'dark' ? 'Chuyển sang Chế độ sáng' : 'Chuyển sang Chế độ tối'}
            >
              <Icon name={theme === 'dark' ? 'light_mode' : 'dark_mode'} className="text-[18px]" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Layout */}
      <div className={`transition-all duration-300 ease-in-out ${sidebarVisible ? 'pl-0 lg:pl-72' : 'pl-0'}`}>
        <main className="w-full pt-16 min-h-screen bg-surface">
          <div className="flex flex-col w-full">
            <div className="relative w-full flex flex-col lg:flex-row items-start min-h-[calc(100vh-4rem)]">
              {/* Center Chat Column */}
              <div className="flex-1 min-w-0 w-full flex justify-center px-4 sm:px-6 lg:px-8 py-6 pb-44">
                <div className="w-full max-w-[840px] flex flex-col gap-6">
                {/* Disclaimer */}
                {disclaimerVisible && (
                  <div className="w-full rounded-2xl bg-surface-container-high/70 backdrop-blur-md p-4 shadow-sm flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3">
                      <div className="w-9 h-9 rounded-xl bg-tertiary-container/30 flex items-center justify-center flex-shrink-0 mt-0.5">
                        <Icon name="gavel" className="text-tertiary text-[20px]" />
                      </div>
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-bold uppercase tracking-wider text-tertiary">Tuyên bố miễn trừ trách nhiệm pháp lý</span>
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-surface-container-highest text-on-surface-variant font-mono">
                            VBPL.VN HYBRID RAG
                          </span>
                        </div>
                        <p className="text-xs leading-relaxed text-on-surface-variant">
                          Thông tin do AI trích xuất và tổng hợp từ hệ thống văn bản quy phạm pháp luật Việt Nam (vbpl.vn), chỉ mang tính chất tham khảo chuyên môn và nghiên cứu, không thay thế văn bản quy phạm pháp luật chính thức hoặc ý kiến tư vấn chính thức của Luật sư có thẻ đoàn.
                        </p>
                      </div>
                    </div>
                    <button
                      className="p-1.5 rounded-lg text-on-surface-variant hover:bg-surface-container-highest hover:text-on-surface transition-colors flex-shrink-0"
                      onClick={() => setDisclaimerVisible(false)}
                      title="Thu gọn thông báo"
                    >
                      <Icon name="close" className="text-[18px]" />
                    </button>
                  </div>
                )}

                {/* Danh sách tin nhắn */}
                {messages.map((msg, idx) => (
                  <div key={idx} className="w-full">
                    {msg.role === 'user' ? (
                      /* User Message */
                      <div className="flex justify-end gap-3 w-full">
                        <div className="flex flex-col items-end max-w-[85%] sm:max-w-[75%] space-y-1.5">
                          <div className="flex items-center gap-2 text-xs text-on-surface-variant">
                            <span className="font-medium text-on-surface">Bạn</span>
                            <span className="font-mono text-[11px]">{msg.timestamp}</span>
                          </div>
                          <div className="p-4 rounded-3xl rounded-tr-sm bg-primary text-on-primary shadow-md text-sm sm:text-[15px] leading-relaxed">
                            {msg.content}
                          </div>
                        </div>
                        <div className="w-9 h-9 rounded-full bg-secondary-container text-on-secondary-container flex items-center justify-center shadow-sm flex-shrink-0">
                          <Icon name="person" className="text-[18px]" />
                        </div>
                      </div>
                    ) : (
                      /* Assistant Message */
                      <div className="flex items-start gap-3 w-full">
                        <div className="relative flex-shrink-0">
                          <div className="w-10 h-10 rounded-2xl bg-gradient-to-tr from-primary to-primary-container p-0.5 shadow-md flex items-center justify-center">
                            <div className="w-full h-full bg-surface-container-lowest rounded-[14px] flex items-center justify-center">
                              <Icon name="balance" className="text-primary text-[22px]" />
                            </div>
                          </div>
                          <div className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full bg-tertiary-container flex items-center justify-center shadow-xs">
                            <Icon name="verified" className="text-[10px] text-on-tertiary-container font-bold" />
                          </div>
                        </div>

                        <div className="flex-1 flex flex-col gap-3 min-w-0">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-bold text-on-surface">Trợ lý Pháp luật</span>
                              {msg.guard_status === 'passed' && (
                                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-tertiary-container/30 text-tertiary">
                                  Đã đối chiếu nguồn
                                </span>
                              )}
                            </div>
                            <span className="text-xs text-on-surface-variant font-mono">{msg.timestamp}</span>
                          </div>




                          {/* Legal Response Box */}
                          <div className="rounded-3xl bg-surface-container-lowest p-6 shadow-md flex flex-col gap-4 text-on-surface">
                            <MarkdownContent content={msg.content} />

                            {/* Căn cứ pháp lý badges nếu có */}
                            {msg.citations && msg.citations.length > 0 && (
                              <div className="space-y-2 pt-2 border-t border-outline-variant/30">
                                <div className="flex items-center justify-between">
                                  <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-on-surface-variant">
                                    <Icon name="menu_book" className="text-[16px]" />
                                    <span>Căn cứ pháp lý viện dẫn</span>
                                  </div>
                                  <span className="text-[11px] text-outline font-mono">{msg.citations.length} Điều luật</span>
                                </div>
                                <div className="flex flex-wrap gap-2">
                                  {msg.citations.map((cite, cIdx) => (
                                    <button
                                      key={cIdx}
                                      onClick={() => {
                                        setInspectorVisible(true);
                                        const isGood = (d: any) =>
                                          d && d.content && !d.content.startsWith('Trích lục điều luật:') && d.content.length > 40;

                                        const foundDoc = msg.retrieved_docs?.find((d) => {
                                          const art = d.article?.trim() || '';
                                          const title = d.article_title?.trim() || '';
                                          const artNum = d.article_number?.trim() || '';
                                          const citeTrim = cite.trim();
                                          return (
                                            isGood(d) &&
                                            ((art && citeTrim.includes(art)) ||
                                              (title && citeTrim.includes(title)) ||
                                              (artNum && citeTrim.includes(artNum)) ||
                                              (d.citation && d.citation === citeTrim))
                                          );
                                        });

                                        if (foundDoc) {
                                          setSelectedDoc(foundDoc);
                                          if (msg.retrieved_docs && msg.retrieved_docs.length > 0) {
                                            setActiveDocList(msg.retrieved_docs.filter(isGood));
                                          }
                                        } else {
                                          setSelectedDoc({
                                            article: cite.split('(')[0].trim(),
                                            article_number: cite,
                                            citation: cite,
                                            law_name: 'Đang truy xuất CSDL Quốc gia VBPL...',
                                            content: 'Đang kết nối cơ sở dữ liệu và tải toàn văn câu chữ điều luật...',
                                            text: 'Đang kết nối cơ sở dữ liệu và tải toàn văn câu chữ điều luật...',
                                          });

                                          fetch(`/api/articles/lookup?citation=${encodeURIComponent(cite)}`)
                                            .then((res) => {
                                              if (!res.ok) throw new Error('Không tìm thấy toàn văn');
                                              return res.json();
                                            })
                                            .then((doc) => {
                                              if (doc && doc.content) {
                                                setSelectedDoc(doc);
                                                if (!msg.retrieved_docs) msg.retrieved_docs = [];
                                                msg.retrieved_docs.push(doc);
                                                setActiveDocList((prev) => [...prev.filter((d) => d.article !== doc.article), doc]);
                                              }
                                            })
                                            .catch(() => {
                                              setSelectedDoc({
                                                article: cite.split('(')[0].trim(),
                                                article_number: cite,
                                                citation: cite,
                                                law_name: 'Văn bản quy phạm pháp luật',
                                                content: `Toàn văn điều luật đang được cập nhật từ Cổng CSDL Quốc gia cho: ${cite}`,
                                                text: `Toàn văn điều luật đang được cập nhật từ Cổng CSDL Quốc gia cho: ${cite}`,
                                              });
                                            });
                                        }
                                      }}
                                      className="group flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-primary-container/30 text-primary hover:bg-primary hover:text-on-primary transition-all duration-200"
                                    >
                                      <Icon name="description" className="text-[14px]" />
                                      <span>{cite}</span>
                                    </button>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Action Toolbar */}
                            <div className="flex flex-wrap items-center justify-between pt-2 border-t border-outline-variant/30 gap-3 text-xs">
                              <div className="flex items-center gap-2 flex-wrap">
                                <button
                                  onClick={() => handlePlayTTS(msg.content, idx)}
                                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl transition-colors font-medium ${
                                    playingIndex === idx
                                      ? 'bg-primary text-on-primary animate-pulse'
                                      : 'bg-surface-container hover:bg-surface-container-high text-on-surface'
                                  }`}
                                  title="Đọc câu trả lời bằng giọng nói tiếng Việt chuẩn AI"
                                >
                                  <Icon name={playingIndex === idx ? 'pause' : 'volume_up'} className="text-[16px]" />
                                  <span>{playingIndex === idx ? 'Đang phát âm thanh...' : 'Nghe câu trả lời'}</span>
                                </button>
                                <button
                                  onClick={() => navigator.clipboard.writeText(msg.content)}
                                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-surface-container hover:bg-surface-container-high text-on-surface transition-colors font-medium"
                                  title="Sao chép câu trả lời"
                                >
                                  <Icon name="content_copy" className="text-[16px]" />
                                  <span>Sao chép</span>
                                </button>
                                <button
                                  onClick={() => window.print()}
                                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-surface-container hover:bg-surface-container-high text-on-surface transition-colors font-medium"
                                  title="In hoặc lưu file PDF"
                                >
                                  <Icon name="download" className="text-[16px]" />
                                  <span>Xuất PDF</span>
                                </button>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                ))}

                {/* Loading Stream Indicator - Thanh tiến trình đa tầng thông minh */}
                {isStreaming && (
                  <div className="flex items-start gap-3 w-full animate-fade-in">
                    <div className="w-10 h-10 rounded-2xl bg-gradient-to-tr from-primary to-primary-container p-0.5 shadow-md flex items-center justify-center flex-shrink-0">
                      <div className="w-full h-full bg-surface-container-lowest rounded-[14px] flex items-center justify-center">
                        <Icon name="balance" className="text-primary text-[22px] animate-spin" />
                      </div>
                    </div>
                    <div className="flex-1 rounded-2xl bg-surface-container-low p-4 sm:p-5 shadow-xs border border-outline-variant/30 space-y-3">
                      {/* Tiêu đề bước & mô tả chi tiết */}
                      <div className="flex items-center justify-between gap-2 flex-wrap">
                        <div className="flex items-center gap-2.5 min-w-0">
                          <div className="w-8 h-8 rounded-xl bg-primary/10 text-primary flex items-center justify-center flex-shrink-0">
                            <Icon
                              name={RAG_PIPELINE_STAGES[progressStageIndex]?.icon || 'psychology'}
                              className="text-[20px] animate-pulse"
                            />
                          </div>
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-bold text-on-surface">
                                Bước {RAG_PIPELINE_STAGES[progressStageIndex]?.step || 1}/
                                {RAG_PIPELINE_STAGES[progressStageIndex]?.totalSteps || 4}:{' '}
                                {RAG_PIPELINE_STAGES[progressStageIndex]?.title}
                              </span>
                            </div>
                            <p className="text-[11px] text-on-surface-variant line-clamp-1 mt-0.5">
                              {RAG_PIPELINE_STAGES[progressStageIndex]?.description}
                            </p>
                          </div>
                        </div>

                        {/* Badge Phần trăm % */}
                        <div className="flex items-center gap-2 flex-shrink-0 ml-auto">
                          <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-bold bg-primary text-on-primary shadow-xs">
                            {Math.round(progressPercent)}%
                          </span>
                        </div>
                      </div>

                      {/* Thanh Progress Bar với hiệu ứng Shimmer ánh sáng */}
                      <div className="space-y-2">
                        <div className="w-full bg-surface-container-highest rounded-full h-2 overflow-hidden relative">
                          <div
                            className="h-full rounded-full bg-gradient-to-r from-primary via-tertiary to-primary transition-all duration-300 ease-out relative overflow-hidden"
                            style={{ width: `${progressPercent}%` }}
                          >
                            <div className="absolute inset-0 bg-white/30 animate-shimmer" />
                          </div>
                        </div>

                        {/* 4 Thẻ trạng thái từng bước của Pipeline */}
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 pt-1">
                          {RAG_PIPELINE_STAGES.map((st, sIdx) => {
                            const isCompleted = progressStageIndex > sIdx;
                            const isCurrent = progressStageIndex === sIdx;
                            return (
                              <div
                                key={st.step}
                                className={`flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-lg transition-all border ${
                                  isCurrent
                                    ? 'bg-primary/10 border-primary/30 text-primary font-bold shadow-xs'
                                    : isCompleted
                                    ? 'bg-surface-container/50 border-transparent text-primary/80 font-medium'
                                    : 'bg-transparent border-transparent text-outline font-normal'
                                }`}
                              >
                                <Icon
                                  name={
                                    isCompleted
                                      ? 'check_circle'
                                      : isCurrent
                                      ? 'hourglass_top'
                                      : 'radio_button_unchecked'
                                  }
                                  className={`text-[14px] flex-shrink-0 ${
                                    isCurrent ? 'animate-spin text-primary' : isCompleted ? 'text-primary' : 'text-outline'
                                  }`}
                                />
                                <span className="truncate">{st.shortName}</span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Follow-up Questions Suggestions */}
                <div className="space-y-2 pt-2">
                  <span className="text-xs font-semibold text-on-surface-variant uppercase tracking-wider flex items-center gap-1.5">
                    <Icon name="auto_awesome" className="text-[16px] text-primary" />
                    <span>Câu hỏi liên quan</span>
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {followupQuestions.map((q, idx) => (
                      <button
                        key={idx}
                        onClick={() => handleSend(q)}
                        className="px-3.5 py-2 rounded-xl bg-surface-container-lowest hover:bg-secondary-container text-xs text-on-surface font-medium transition-all shadow-xs flex items-center gap-2"
                      >
                        <span>{q}</span>
                        <Icon name="arrow_outward" className="text-[14px] text-primary" />
                      </button>
                    ))}
                  </div>
                </div>

                  <div ref={chatEndRef} />
                </div>
              </div>

              {/* Right: Source Inspector */}
              {inspectorVisible && (
                <div className="w-full lg:w-[400px] xl:w-[420px] lg:h-[calc(100vh-4rem)] lg:sticky lg:top-16 bg-surface-container-lowest shadow-xl flex flex-col z-30 flex-shrink-0 border-l border-outline-variant/30">
                  {/* Drawer Header */}
                  <div className="p-4 bg-surface-container-low flex items-center justify-between border-b border-outline-variant/30">
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="w-8 h-8 rounded-lg bg-primary text-on-primary flex items-center justify-center flex-shrink-0">
                        <Icon name="verified" className="text-[18px]" />
                      </div>
                      <div className="min-w-0">
                        <h2 className="text-sm font-bold text-on-surface truncate">Kiểm tra nguồn văn bản gốc VBPL</h2>
                        <p className="text-[11px] text-on-surface-variant font-mono">Đối chiếu từng câu chữ điều luật</p>
                      </div>
                    </div>
                    <button
                      className="p-1.5 rounded-lg text-on-surface-variant hover:bg-surface-container-high transition-colors"
                      onClick={() => setInspectorVisible(false)}
                      title="Đóng bảng nguồn"
                    >
                      <Icon name="close" className="text-[18px]" />
                    </button>
                  </div>

                  {/* Drawer Scrollable Content */}
                  <div className="flex-1 overflow-y-auto p-4 space-y-4 text-on-surface">
                    {/* Multi-Article Tabs Quick Switcher with Drag & Horizontal Scroll */}
                    {activeDocList.length > 1 && (
                      <div className="space-y-1.5 pb-2.5 border-b border-outline-variant/30">
                        <div className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-on-surface-variant px-0.5">
                          <Icon name="layers" className="text-[14px] text-primary" />
                          <span>Điều luật liên quan ({activeDocList.length}):</span>
                        </div>

                        {/* Horizontal Scroll Bar with Left/Right Arrow Controls */}
                        <div className="relative flex items-center group/tabbar">
                          {/* Left Scroll Arrow Button */}
                          {canScrollLeft && (
                            <button
                              type="button"
                              onClick={() => scrollTabs(-130)}
                              className="absolute left-0 z-10 w-6 h-6 rounded-full bg-surface-container-high/95 hover:bg-primary hover:text-on-primary text-on-surface shadow-md flex items-center justify-center transition-all -ml-1 border border-outline-variant/40 backdrop-blur-xs"
                              title="Cuộn sang trái"
                            >
                              <Icon name="chevron_left" className="text-[16px]" />
                            </button>
                          )}

                          {/* Draggable & Scrollable Container */}
                          <div
                            ref={tabsContainerRef}
                            onScroll={checkTabsScroll}
                            onWheel={handleTabsWheel}
                            onMouseDown={handleTabsMouseDown}
                            onMouseMove={handleTabsMouseMove}
                            onMouseUp={handleTabsMouseUp}
                            onMouseLeave={handleTabsMouseUp}
                            className="flex items-center gap-1.5 overflow-x-auto py-1 px-0.5 select-none cursor-grab active:cursor-grabbing w-full scroll-smooth"
                            style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
                          >
                            {activeDocList.map((doc, dIdx) => {
                              const isSelected =
                                selectedDoc &&
                                ((doc.id && doc.id === selectedDoc.id) ||
                                  (doc.article && doc.article === selectedDoc.article) ||
                                  (doc.article_number && doc.article_number === selectedDoc.article_number));
                              const artLabel = doc.article || `Điều ${dIdx + 1}`;
                              const artTooltip = doc.article_title ? `${artLabel}: ${doc.article_title}` : artLabel;
                              return (
                                <button
                                  key={dIdx}
                                  data-selected={isSelected ? 'true' : 'false'}
                                  onClick={() => {
                                    if (tabsHasMovedRef.current) return;
                                    setSelectedDoc(doc);
                                  }}
                                  title={artTooltip}
                                  className={`px-3 py-1.5 rounded-xl text-xs font-semibold whitespace-nowrap transition-all flex items-center gap-1.5 flex-shrink-0 ${
                                    isSelected
                                      ? 'bg-primary text-on-primary shadow-sm scale-[1.02]'
                                      : 'bg-surface-container hover:bg-surface-container-high text-on-surface hover:text-primary'
                                  }`}
                                >
                                  <Icon name="description" className="text-[14px]" />
                                  <span>{artLabel}</span>
                                </button>
                              );
                            })}
                          </div>

                          {/* Right Scroll Arrow Button */}
                          {canScrollRight && (
                            <button
                              type="button"
                              onClick={() => scrollTabs(130)}
                              className="absolute right-0 z-10 w-6 h-6 rounded-full bg-surface-container-high/95 hover:bg-primary hover:text-on-primary text-on-surface shadow-md flex items-center justify-center transition-all -mr-1 border border-outline-variant/40 backdrop-blur-xs"
                              title="Cuộn sang phải"
                            >
                              <Icon name="chevron_right" className="text-[16px]" />
                            </button>
                          )}
                        </div>
                      </div>
                    )}

                    {selectedDoc ? (
                      <>
                        {/* Legal Metadata Header Card */}
                        <div className="p-3.5 rounded-2xl bg-surface-container-low space-y-2 border border-outline-variant/20 shadow-xs">
                          <div className="flex items-center justify-between">
                            <span className="px-2 py-0.5 rounded-md bg-secondary-container text-on-secondary-container font-mono text-[10px] font-bold">
                              CSDL QUỐC GIA VBPL
                            </span>
                            <div className="flex items-center gap-1 text-xs font-bold text-tertiary">
                              <Icon name="verified" className="text-[15px]" />
                              <span>
                                {selectedDoc.score ? `${(selectedDoc.score * 100).toFixed(1)}% độ khớp` : 'Đã xác thực'}
                              </span>
                            </div>
                          </div>
                          <div>
                            <div className="flex items-center gap-1.5 text-xs text-primary font-bold">
                              <Icon name="gavel" className="text-[15px]" />
                              <span>{selectedDoc.law_name || 'Văn bản quy phạm pháp luật'}</span>
                            </div>
                            <h3 className="text-sm font-bold text-on-surface mt-1">
                              {selectedDoc.article ? `${selectedDoc.article}${selectedDoc.article_title ? `: ${selectedDoc.article_title}` : ''}` : selectedDoc.article_number || 'Nội dung điều luật'}
                            </h3>
                          </div>
                        </div>

                        {/* Full Article Content */}
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold uppercase tracking-wider text-on-surface-variant flex items-center gap-1.5">
                              <Icon name="menu_book" className="text-[15px] text-primary" />
                              <span>
                                {contentViewMode === 'focused' && selectedDoc.focused_content
                                  ? 'Đoạn quy định trọng tâm'
                                  : 'Toàn văn nội dung điều luật'}
                              </span>
                            </span>

                            <div className="flex items-center gap-1.5">
                              {/* Toggle between full and focused snippet if available */}
                              {selectedDoc.focused_content && selectedDoc.content && selectedDoc.focused_content !== selectedDoc.content && (
                                <button
                                  onClick={() => setContentViewMode((m) => (m === 'full' ? 'focused' : 'full'))}
                                  className="px-2 py-0.5 rounded-md text-[11px] font-medium bg-surface-container hover:bg-surface-container-high text-primary transition-colors"
                                  title="Chuyển đổi giữa đoạn trích trọng tâm và toàn văn"
                                >
                                  {contentViewMode === 'full' ? 'Xem tóm lược' : 'Xem toàn văn'}
                                </button>
                              )}

                              {/* Copy button */}
                              <button
                                onClick={() => {
                                  const textToCopy =
                                    contentViewMode === 'focused' && selectedDoc.focused_content
                                      ? selectedDoc.focused_content
                                      : selectedDoc.content || selectedDoc.text || '';
                                  navigator.clipboard.writeText(textToCopy);
                                  setCopiedDoc(true);
                                  setTimeout(() => setCopiedDoc(false), 2000);
                                }}
                                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                                  copiedDoc
                                    ? 'bg-secondary-container text-on-secondary-container font-semibold'
                                    : 'bg-surface-container hover:bg-surface-container-high text-on-surface'
                                }`}
                                title="Sao chép toàn bộ câu chữ điều luật"
                              >
                                <Icon name={copiedDoc ? 'check' : 'content_copy'} className="text-[14px] text-primary" />
                                <span>{copiedDoc ? 'Đã chép' : 'Sao chép'}</span>
                              </button>
                            </div>
                          </div>

                          <div className="p-4 rounded-2xl bg-surface-container text-xs sm:text-[13px] leading-relaxed space-y-2 shadow-inner whitespace-pre-wrap font-sans text-on-surface border border-outline-variant/30 select-text max-h-[520px] overflow-y-auto">
                            {(contentViewMode === 'focused' && selectedDoc.focused_content)
                              ? selectedDoc.focused_content
                              : (selectedDoc.content || selectedDoc.text || 'Đang cập nhật toàn văn điều luật từ cơ sở dữ liệu...')}
                          </div>
                        </div>
                      </>
                    ) : (
                      <div className="p-8 text-center text-on-surface-variant text-xs space-y-2">
                        <Icon name="menu_book" className="text-[32px] text-outline mx-auto" />
                        <p>Bấm vào bất kỳ Căn cứ pháp lý nào trong câu trả lời để mở toàn văn điều luật đối chiếu tại đây.</p>
                      </div>
                    )}
                  </div>

                  {/* Drawer Footer: Nguồn thẩm định tinh gọn */}
                  <div className="p-3.5 bg-surface-container-low flex items-center justify-between text-[11px] text-on-surface-variant border-t border-outline-variant/30">
                    <span className="flex items-center gap-1 font-medium">
                      <Icon name="verified" className="text-[14px] text-primary" />
                      <span>Trích lục nguyên văn CSDL Quốc gia</span>
                    </span>
                    <a
                      href="https://vbpl.vn"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary hover:underline flex items-center gap-0.5"
                      title="Mở Cổng CSDL Quốc gia về văn bản pháp luật"
                    >
                      <span>Cổng VBPL.vn</span>
                      <Icon name="open_in_new" className="text-[12px]" />
                    </a>
                  </div>
                </div>
              )}
            </div>
          </div>
        </main>
      </div>

      {/* Floating Input Bar */}
      <div
        className={`fixed bottom-0 left-0 right-0 px-4 sm:px-6 lg:px-8 py-4 bg-gradient-to-t from-surface via-surface/95 to-transparent z-40 flex flex-col items-center pointer-events-none transition-all duration-300 ease-in-out ${
          sidebarVisible ? 'lg:left-72' : 'lg:left-0'
        } ${
          inspectorVisible ? 'lg:right-[400px] xl:right-[420px]' : ''
        }`}
      >
        <div className="w-full max-w-[840px] pointer-events-auto space-y-2">
          <div className="rounded-3xl bg-surface-container-lowest shadow-xl p-2.5 flex flex-col gap-2 border border-outline-variant/30">
            {/* Textarea Row */}
            <div className="flex items-end gap-2 px-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                className="flex-1 bg-transparent text-sm text-on-surface placeholder:text-outline resize-none focus:outline-none leading-relaxed py-1.5"
                placeholder={
                  isListening
                    ? 'Đang lắng nghe giọng nói tiếng Việt... Hãy nói câu hỏi của bạn!'
                    : 'Nhập tình huống pháp lý hoặc đặt câu hỏi tư vấn (Enter để gửi)...'
                }
                rows={2}
              />
              <div className="flex items-center gap-1.5 pb-1">
                <button
                  onClick={toggleSpeechRecognition}
                  className={`w-9 h-9 rounded-xl flex items-center justify-center transition-colors ${
                    isListening
                      ? 'bg-error text-on-error animate-bounce'
                      : 'text-on-surface-variant hover:bg-surface-container hover:text-primary'
                  }`}
                  title={isListening ? 'Dừng ghi âm' : 'Nhập liệu bằng giọng nói tiếng Việt (Micro)'}
                >
                  <Icon name={isListening ? 'mic_off' : 'mic'} className="text-[20px]" />
                </button>
                <button
                  onClick={() => handleSend()}
                  disabled={!input.trim() || isStreaming}
                  className="w-10 h-10 rounded-xl bg-gradient-to-r from-primary to-primary-container text-on-primary shadow-md hover:shadow-lg flex items-center justify-center transition-all hover:scale-[1.05] disabled:opacity-50 disabled:hover:scale-100"
                  title="Gửi câu hỏi tra cứu (Enter)"
                >
                  <Icon name="send" className="text-[20px]" />
                </button>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-center gap-2 text-[10px] text-outline font-mono text-center">
            <span>Hệ thống tra cứu và tham vấn dựa trên CSDL Văn bản Quy phạm Pháp luật Quốc gia</span>
          </div>
        </div>
      </div>

      {/* Modal Xác nhận Xóa Phiên hội thoại */}
      {sessionToDelete && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm transition-opacity"
          onClick={() => {
            if (!isDeletingSession) setSessionToDelete(null);
          }}
        >
          <div
            className="w-full max-w-sm sm:max-w-md bg-surface-container-lowest rounded-3xl p-6 shadow-2xl border border-outline-variant/30 flex flex-col gap-4 animate-in zoom-in-95 duration-150"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3.5">
              <div className="w-12 h-12 rounded-2xl bg-error/10 text-error flex items-center justify-center flex-shrink-0">
                <Icon name="delete_forever" className="text-[26px]" />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-base font-bold text-on-surface">Xóa phiên hội thoại?</h3>
                <p className="text-xs text-on-surface-variant mt-1 leading-relaxed">
                  Bạn có chắc chắn muốn xóa phiên này? Toàn bộ lịch sử hỏi đáp và các văn bản đã trích xuất trong phiên sẽ bị xóa vĩnh viễn.
                </p>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-outline-variant/20">
              <button
                type="button"
                onClick={() => setSessionToDelete(null)}
                disabled={isDeletingSession}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-on-surface-variant hover:bg-surface-container transition-colors disabled:opacity-50"
              >
                Hủy bỏ
              </button>
              <button
                type="button"
                onClick={confirmDeleteSession}
                disabled={isDeletingSession}
                className="px-4 py-2 rounded-xl text-xs font-semibold bg-error text-on-error hover:bg-error/90 shadow-sm transition-all flex items-center gap-1.5 disabled:opacity-50"
              >
                {isDeletingSession ? (
                  <>
                    <Icon name="sync" className="text-[16px] animate-spin" />
                    <span>Đang xóa...</span>
                  </>
                ) : (
                  <>
                    <Icon name="delete" className="text-[16px]" />
                    <span>Xác nhận xóa</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
