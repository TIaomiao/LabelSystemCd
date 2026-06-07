
export interface StreamEvent {
  type: string;
  timestamp: string;
  workflow_tag?: string;
  content: any;
}

export async function streamDiagnosis(
  caseId: string,
  prompt: string | null,
  onEvent: (event: StreamEvent) => void,
  onDone: () => void,
  onError: (error: Error) => void
) {
  try {
    const response = await fetch('/api/diagnose', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        case_id: caseId,
        prompt: prompt
      }),
    });

    if (!response.ok) {
      throw new Error(`Diagnosis failed to start (${response.status})`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('ReadableStream not supported');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const jsonStr = line.slice(6);
          try {
            const event = JSON.parse(jsonStr);
            onEvent(event);
          } catch (e) {
            console.error('Failed to parse SSE event:', e);
          }
        }
      }
    }
    
    onDone();
  } catch (err) {
    onError(err instanceof Error ? err : new Error(String(err)));
  }
}
