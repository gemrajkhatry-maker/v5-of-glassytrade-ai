import type { ProjectionEnvelope } from "../generated/ws_v1";

export interface ProjectionSocket {
  close(): void;
  onmessage: ((event: MessageEvent<string>) => void) | null;
  onerror: ((event: Event) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
}

export type SocketFactory = (url: string) => ProjectionSocket;

export class ProjectionClient {
  private socket: ProjectionSocket | null = null;

  constructor(
    private readonly url: string,
    private readonly onMessage: (message: ProjectionEnvelope) => void,
    private readonly onResnapshot: () => void = () => undefined,
    private readonly socketFactory: SocketFactory = (value) =>
      new WebSocket(value) as unknown as ProjectionSocket,
  ) {}

  connect(): void {
    if (this.socket) return;
    const socket = this.socketFactory(this.url);
    this.socket = socket;
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data) as ProjectionEnvelope;
      if (message.type === "delta" && message.baseSequence === null) {
        this.onResnapshot();
        return;
      }
      this.onMessage(message);
    };
    socket.onerror = () => this.onResnapshot();
  }

  close(): void {
    this.socket?.close();
    this.socket = null;
  }
}
