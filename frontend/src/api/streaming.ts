type EventHandler = (data: unknown) => void;

export interface Stream {
  on(event: string, handler: EventHandler): void;
  close(): void;
}

export function createStream(path: string): Stream {
  let es: EventSource | null = null;
  let retryMs = 1000;
  let closed = false;
  const handlers: Record<string, EventHandler[]> = {};

  function connect() {
    if (closed) return;
    es = new EventSource(path, { withCredentials: true });

    es.onopen = () => {
      retryMs = 1000;
    };

    es.addEventListener("update", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        handlers["update"]?.forEach((h) => h(data));
      } catch { /* ignore parse errors */ }
    });

    es.addEventListener("notification", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        handlers["notification"]?.forEach((h) => h(data));
      } catch { /* ignore parse errors */ }
    });

    es.onerror = () => {
      es?.close();
      if (!closed) {
        setTimeout(connect, retryMs);
        retryMs = Math.min(retryMs * 2, 30000);
      }
    };
  }

  function on(event: string, handler: EventHandler) {
    (handlers[event] ??= []).push(handler);
  }

  function close() {
    closed = true;
    es?.close();
    es = null;
  }

  connect();
  return { on, close };
}
