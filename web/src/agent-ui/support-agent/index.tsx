import React, { useState } from 'react';
import { Button, Card, Icon } from '../../asaas-ui';
import { useAgentRun } from '../../agent-sdk';
import { SafeMarkdown } from '../../components/SafeMarkdown';

interface MessageItem {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

const QUICK_PROMPTS = [
  'كيف يمكنني إعادة تعيين كلمة المرور في حسابي؟',
  'لدي استفسار حول فواتير الاشتراك الشهري وطرق الدفع.',
  'كيف يمكنني توليد مفتاح API جديد للربط التقني؟',
];

export default function SupportAgentPlayground() {
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [inputText, setInputText] = useState('');

  const {
    run,
    cancel,
    statusDetail,
    isRunning,
    steps,
    streamingText,
    result,
    error,
    reset,
  } = useAgentRun('support-agent');

  const handleSend = async (textToSend?: string) => {
    const text = (textToSend || inputText).trim();
    if (!text || isRunning) return;

    const userMsg: MessageItem = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
    };
    setMessages((prev) => [...prev, userMsg]);
    setInputText('');

    await run({ message: text });
  };

  // Sync result into messages when finished
  React.useEffect(() => {
    if (result && result.content) {
      setMessages((prev) => {
        // Prevent duplicate appending
        const last = prev[prev.length - 1];
        if (last && last.role === 'assistant' && last.content === result.content) {
          return prev;
        }
        return [
          ...prev,
          {
            id: `asst-${Date.now()}`,
            role: 'assistant',
            content: result.content,
          },
        ];
      });
    }
  }, [result]);

  const handleReset = () => {
    reset();
    setMessages([]);
    setInputText('');
  };

  return (
    <Card title="تجربة وكيل خدمة العملاء" icon="phone" className="agent-playground-card">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {/* Quick Suggestion Chips */}
        {messages.length === 0 && (
          <div>
            <span className="subtle" style={{ display: 'block', marginBottom: '8px', fontWeight: 600 }}>
              اقتراحات سريعة للبدء:
            </span>
            <div className="chips">
              {QUICK_PROMPTS.map((prompt, idx) => (
                <button
                  key={idx}
                  type="button"
                  className="chip"
                  onClick={() => handleSend(prompt)}
                  disabled={isRunning}
                >
                  <Icon name="sparkle" />
                  <span>{prompt}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Conversation Stream */}
        <div
          className="chat-thread"
          style={{
            minHeight: '220px',
            maxHeight: '480px',
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
            padding: '12px',
            borderRadius: 'var(--radius-md)',
            background: 'var(--glass-inset)',
            boxShadow: 'inset 0 0 0 1px var(--hairline)',
          }}
        >
          {messages.length === 0 && !isRunning && (
            <div style={{ margin: 'auto', textAlign: 'center', color: 'var(--text-3)', padding: '24px' }}>
              <Icon name="sparkle" style={{ width: '28px', height: '28px', color: 'var(--accent)', marginBottom: '8px' }} />
              <p>أدخل استفسارك أو اختر من الاقتراحات أعلاه لبدء المحادثة مع الوكيل.</p>
            </div>
          )}

          {messages.map((m) => (
            <div
              key={m.id}
              style={{
                alignSelf: m.role === 'user' ? 'flex-start' : 'flex-end',
                maxWidth: '85%',
                padding: '10px 16px',
                borderRadius: 'var(--radius-lg)',
                background: m.role === 'user' ? 'var(--accent-glow)' : 'var(--glass-tint)',
                border: '1px solid var(--hairline)',
                color: 'var(--text-1)',
              }}
            >
              <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--accent)', marginBottom: '4px' }}>
                {m.role === 'user' ? 'أنت' : 'وكيل الدعم'}
              </div>
              <SafeMarkdown content={m.content} />
            </div>
          ))}

          {/* Real-time Streaming Delta Bubble */}
          {isRunning && (
            <div
              style={{
                alignSelf: 'flex-end',
                maxWidth: '85%',
                padding: '10px 16px',
                borderRadius: 'var(--radius-lg)',
                background: 'var(--glass-tint)',
                border: '1px solid var(--accent)',
                boxShadow: '0 2px 12px -2px var(--accent-glow)',
              }}
            >
              <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--accent)', marginBottom: '4px' }}>
                وكيل الدعم (جاري الإجابة...)
              </div>
              {streamingText ? (
                <SafeMarkdown content={streamingText} />
              ) : (
                <p className="subtle" style={{ fontStyle: 'italic', margin: 0 }}>
                  {statusDetail || 'جاري التفكير والتوليد...'}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Live Step Progress Badges */}
        {steps.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <span className="subtle" style={{ fontWeight: 600 }}>خطوات واستدعاءات الوكيل:</span>
            <div className="chips">
              {steps.map((st, i) => (
                <span key={i} className="pill pill--neutral">
                  <Icon name="checkCircle" />
                  <span>خطوة {st.step_number}: {st.tool}</span>
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Error Notification */}
        {error && (
          <div
            style={{
              padding: '10px 14px',
              borderRadius: 'var(--radius-md)',
              background: 'var(--unpaid-bg)',
              color: 'var(--unpaid)',
              fontSize: '13px',
              fontWeight: 600,
            }}
          >
            {error}
          </div>
        )}

        {/* Input Bar */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          style={{ display: 'flex', gap: '10px', alignItems: 'center' }}
        >
          <input
            type="text"
            className="search-input"
            style={{
              flex: 1,
              height: '44px',
              paddingInline: '16px',
              borderRadius: 'var(--radius-pill)',
              background: 'var(--glass-tint)',
              border: '1px solid var(--hairline)',
              color: 'var(--text-1)',
              outline: 'none',
            }}
            placeholder="اكتب استفسارك لوكيل الدعم هنا..."
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            disabled={isRunning}
          />

          {isRunning ? (
            <Button variant="danger" icon="close" onClick={cancel} type="button">
              إلغاء
            </Button>
          ) : (
            <Button variant="primary" icon="send" type="submit" disabled={!inputText.trim()}>
              إرسال
            </Button>
          )}

          {messages.length > 0 && !isRunning && (
            <Button variant="ghost" icon="trash" onClick={handleReset} type="button" label="مسح المحادثة" />
          )}
        </form>
      </div>
    </Card>
  );
}
