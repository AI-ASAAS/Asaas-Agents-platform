import React, { useRef, useState } from 'react';
import { Button, Card, Icon } from '../../asaas-ui';
import { useAgentRun } from '../../agent-sdk';
import { SafeMarkdown } from '../../components/SafeMarkdown';

export default function DocumentAnalyzerPlayground() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [prompt, setPrompt] = useState(
    'قم بتحليل محتوى هذا المستند واستخراج ملخص تنفيذي مع أهم المؤشرات والأرقام.'
  );
  const fileInputRef = useRef<HTMLInputElement | null>(null);

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
  } = useAgentRun('document-analyzer');

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
    }
  };

  const handleRun = async () => {
    if (isRunning) return;
    await run({
      message: prompt,
      files: selectedFile ? [selectedFile] : undefined,
    });
  };

  const handleReset = () => {
    reset();
    setSelectedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  return (
    <Card title="تجربة وكيل تحليل الوثائق والتقارير" icon="receipt" className="agent-playground-card">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {/* File Picker Section */}
        <div
          style={{
            border: '2px dashed var(--hairline)',
            borderRadius: 'var(--radius-md)',
            padding: '20px',
            textAlign: 'center',
            background: 'var(--glass-inset)',
            cursor: 'pointer',
          }}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept=".pdf,.png,.jpg,.jpeg"
            style={{ display: 'none' }}
          />
          <Icon name="file" style={{ width: '32px', height: '32px', color: 'var(--accent)', marginBottom: '8px' }} />
          {selectedFile ? (
            <div>
              <p style={{ fontWeight: 700, color: 'var(--text-1)' }}>{selectedFile.name}</p>
              <p className="subtle">{(selectedFile.size / 1024).toFixed(1)} KB — جاهز للتحليل</p>
            </div>
          ) : (
            <div>
              <p style={{ fontWeight: 600, color: 'var(--text-1)' }}>انقر لاختيار مستند أو تقرير (PDF أو صورة)</p>
              <p className="subtle">الحد الأقصى 10 ميجابايت (يتم فحص التوقيع الرقمي للملف)</p>
            </div>
          )}
        </div>

        {/* Instructions Input */}
        <div>
          <label className="subtle" style={{ display: 'block', marginBottom: '6px', fontWeight: 600 }}>
            تعليمات التحليل:
          </label>
          <textarea
            rows={3}
            className="search-input"
            style={{
              width: '100%',
              borderRadius: 'var(--radius-md)',
              padding: '12px',
              boxSizing: 'border-box',
              background: 'var(--glass-tint)',
              border: '1px solid var(--hairline)',
              color: 'var(--text-1)',
              fontFamily: 'inherit',
              fontSize: '14px',
              outline: 'none',
              resize: 'vertical',
            }}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={isRunning}
          />
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
          {isRunning ? (
            <Button variant="danger" icon="close" onClick={cancel}>
              إلغاء التحليل
            </Button>
          ) : (
            <Button variant="primary" icon="sparkle" onClick={handleRun}>
              بدء فحص وتحليل المستند
            </Button>
          )}

          {result && !isRunning && (
            <Button variant="ghost" icon="trash" onClick={handleReset}>
              تحليل مستند جديد
            </Button>
          )}

          {statusDetail && (
            <span className="subtle" style={{ marginInlineStart: 'auto' }}>
              {statusDetail}
            </span>
          )}
        </div>

        {/* Tool Execution Steps */}
        {steps.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <span className="subtle" style={{ fontWeight: 600 }}>مراحل الاستخراج والمعالجة:</span>
            <div className="chips">
              {steps.map((st, i) => (
                <span key={i} className="pill pill--paid">
                  <Icon name="check" />
                  <span>مرحلة {st.step_number}: {st.tool}</span>
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

        {/* Real-time Streaming Output / Result */}
        {(streamingText || (result && result.content)) && (
          <div
            style={{
              padding: '16px',
              borderRadius: 'var(--radius-md)',
              background: 'var(--glass-tint)',
              border: '1px solid var(--hairline)',
            }}
          >
            <h4 style={{ margin: '0 0 10px 0', fontSize: '15px', fontWeight: 700, color: 'var(--accent)' }}>
              نتائج تقرير التحليل:
            </h4>
            <SafeMarkdown content={result?.content || streamingText} />

            {/* Extracted Artifacts */}
            {result?.artifacts && result.artifacts.length > 0 && (
              <div style={{ marginTop: '16px', paddingTop: '12px', borderTop: '1px solid var(--hairline)' }}>
                {result.artifacts.map((art, idx) => (
                  <div key={idx}>
                    {art.type === 'summary_card' && (
                      <div className="grid grid--stats" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '10px', marginTop: '8px' }}>
                        {art.metrics?.map((m: any, mi: number) => (
                          <div key={mi} style={{ padding: '10px', borderRadius: 'var(--radius-sm)', background: 'var(--glass-inset)' }}>
                            <div className="subtle">{m.label}</div>
                            <div style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-1)' }}>{m.value}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
