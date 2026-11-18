import { useCallback, useEffect, useRef, useState } from 'react';
import type { UsageInfo } from '../lib/providerApi';
import { sessionKeyStore } from '../lib/sessionKeyStore';
import { recordSessionUsage } from '../lib/useUsageTracker';

export interface AgentRunStep {
  step_number: number;
  tool: string;
  input?: Record<string, any>;
  output?: Record<string, any>;
}

export interface AgentRunResult {
  content: string;
  artifacts?: Array<Record<string, any>>;
}

export interface RunInputOptions {
  message: string;
  parameters?: Record<string, any>;
  files?: File[];
}

export type RunStatus =
  | 'idle'
  | 'starting'
  | 'thinking'
  | 'calling_tool'
  | 'generating'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface UseAgentRunReturn {
  run: (options: RunInputOptions) => Promise<void>;
  cancel: () => Promise<void>;
  status: RunStatus;
  statusDetail: string | null;
  isRunning: boolean;
  steps: AgentRunStep[];
  streamingText: string;
  result: AgentRunResult | null;
  error: string | null;
  usage: UsageInfo | null;
  reset: () => void;
}

export function useAgentRun(slug: string): UseAgentRunReturn {
  const [status, setStatus] = useState<RunStatus>('idle');
  const [statusDetail, setStatusDetail] = useState<string | null>(null);
  const [steps, setSteps] = useState<AgentRunStep[]>([]);
  const [streamingText, setStreamingText] = useState<string>('');
  const [result, setResult] = useState<AgentRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [usage, setUsage] = useState<UsageInfo | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  // Clean up on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const reset = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setStatus('idle');
    setStatusDetail(null);
    setSteps([]);
    setStreamingText('');
    setResult(null);
    setError(null);
    setUsage(null);
  }, []);

  const cancel = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setStatus('cancelled');
    setStatusDetail('تم إلغاء التجربة.');
  }, []);

  const run = useCallback(
    async ({ message, parameters, files }: RunInputOptions) => {
      const creds = sessionKeyStore.getCredentials();
      if (!creds || !creds.provider || !creds.key) {
        setError('يرجى اختيار مزود الخدمة وإدخال مفتاح API أولاً.');
        setStatus('failed');
        return;
      }
      if (!creds.model) {
        setError('يرجى اختيار نموذج متوافق لبدء التجربة.');
        setStatus('failed');
        return;
      }

      // Reset state
      setStatus('starting');
      setStatusDetail('بدء تشغيل الوكيل...');
      setSteps([]);
      setStreamingText('');
      setResult(null);
      setError(null);

      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      try {
        let body: BodyInit;
        const headers: Record<string, string> = {
          'X-Provider': creds.provider,
          'X-Provider-Key': creds.key,
          'X-Model': creds.model,
        };

        if (files && files.length > 0) {
          const formData = new FormData();
          formData.append('message', message);
          formData.append('model', creds.model);
          if (parameters) {
            formData.append('parameters', JSON.stringify(parameters));
          }
          files.forEach((f, idx) => {
            formData.append(`file_${idx}`, f, f.name);
          });
          body = formData;
        } else {
          headers['Content-Type'] = 'application/json';
          body = JSON.stringify({
            message,
            model: creds.model,
            parameters: parameters || {},
          });
        }

        const resp = await fetch(`/api/agents/${encodeURIComponent(slug)}/run`, {
          method: 'POST',
          headers,
          body,
          signal: abortController.signal,
        });

        if (!resp.ok) {
          let errMsg = `فشل تشغيل الوكيل (${resp.status})`;
          try {
            const errJson = await resp.json();
            if (errJson.message) errMsg = errJson.message;
          } catch {
            // ignore
          }
          setError(errMsg);
          setStatus('failed');
          return;
        }

        if (!resp.body) {
          setError('لم يتم استلام استجابة متدفقة من الخادم.');
          setStatus('failed');
          return;
        }

        // Read SSE stream
        const reader = resp.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split('\n\n');
          buffer = parts.pop() || '';

          for (const block of parts) {
            if (!block.trim()) continue;
            const lines = block.split('\n');
            let eventType = 'message';
            let dataStr = '';

            for (const line of lines) {
              if (line.startsWith('event:')) {
                eventType = line.slice(6).trim();
              } else if (line.startsWith('data:')) {
                dataStr = line.slice(5).trim();
              }
            }

            if (!dataStr) continue;

            let dataObj: any;
            try {
              dataObj = JSON.parse(dataStr);
            } catch {
              continue;
            }

            switch (eventType) {
              case 'status':
                setStatus(dataObj.state || 'running');
                setStatusDetail(dataObj.detail || null);
                break;

              case 'message_delta':
                if (dataObj.delta) {
                  setStreamingText((prev) => prev + dataObj.delta);
                }
                break;

              case 'step':
                setSteps((prev) => [...prev, dataObj]);
                break;

              case 'result':
                setResult(dataObj);
                setStatus('completed');
                setStatusDetail('اكتملت التجربة بنجاح.');
                break;

              case 'usage':
                setUsage(dataObj);
                // Record in global session usage tracker to update the UsagePanel
                recordSessionUsage(dataObj);
                break;

              case 'error':
                setError(dataObj.message || dataObj.code || 'حدث خطأ أثناء التنفيذ.');
                setStatus('failed');
                break;

              case 'done':
                break;
            }
          }
        }
      } catch (err: any) {
        if (err.name === 'AbortError') {
          setStatus('cancelled');
          setStatusDetail('تم إلغاء التجربة.');
        } else {
          setError(err.message || 'حدث خطأ أثناء الاتصال بالخادم.');
          setStatus('failed');
        }
      } finally {
        abortControllerRef.current = null;
      }
    },
    [slug]
  );

  const isRunning = status === 'starting' || status === 'thinking' || status === 'calling_tool' || status === 'generating';

  return {
    run,
    cancel,
    status,
    statusDetail,
    isRunning,
    steps,
    streamingText,
    result,
    error,
    usage,
    reset,
  };
}
