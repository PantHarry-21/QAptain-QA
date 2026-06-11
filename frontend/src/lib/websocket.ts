/**
 * QAptain WebSocket Client
 * Real-time event stream from backend.
 */

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws';

type EventHandler = (data: Record<string, unknown>) => void;

class QAptainWebSocket {
  private ws: WebSocket | null = null;
  private clientId: string;
  private handlers: Map<string, Set<EventHandler>> = new Map();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 2000;
  private maxReconnectDelay = 30000;
  private subscriptions: Set<string> = new Set();

  constructor() {
    this.clientId = `client_${Math.random().toString(36).slice(2, 10)}`;
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    this.ws = new WebSocket(`${WS_URL}/${this.clientId}`);

    this.ws.onopen = () => {
      console.log('[QAptain WS] Connected');
      this.reconnectDelay = 2000;
      // Re-subscribe to all topics after reconnect
      for (const topic of this.subscriptions) {
        this.send({ subscribe: topic });
      }
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const eventType = data.event as string;
        if (eventType) {
          this.emit(eventType, data);
          this.emit('*', data); // Wildcard handler
        }
      } catch {
        // ignore parse errors
      }
    };

    this.ws.onclose = () => {
      console.log('[QAptain WS] Disconnected — reconnecting in', this.reconnectDelay, 'ms');
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  disconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }

  subscribe(topic: string): void {
    this.subscriptions.add(topic);
    this.send({ subscribe: topic });
  }

  on(event: string, handler: EventHandler): () => void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set());
    }
    this.handlers.get(event)!.add(handler);
    return () => this.off(event, handler);
  }

  off(event: string, handler: EventHandler): void {
    this.handlers.get(event)?.delete(handler);
  }

  private emit(event: string, data: Record<string, unknown>): void {
    this.handlers.get(event)?.forEach((h) => h(data));
  }

  private send(data: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  private scheduleReconnect(): void {
    this.reconnectTimer = setTimeout(() => {
      this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, this.maxReconnectDelay);
      this.connect();
    }, this.reconnectDelay);
  }
}

// Singleton
let _socket: QAptainWebSocket | null = null;

export function getSocket(): QAptainWebSocket {
  if (!_socket) {
    _socket = new QAptainWebSocket();
  }
  return _socket;
}

export { QAptainWebSocket };
