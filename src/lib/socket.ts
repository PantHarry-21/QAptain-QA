import { Server } from 'socket.io';
import { executeTests } from './test-executor';

interface StartTestPayload {
  sessionId: string;
  scenarios: any[];
  url: string;
}

export const setupSocket = (io: Server) => {
  io.on('connection', (socket) => {
    console.log(`Client connected: ${socket.id}`);

    // Join a room for a specific test session
    socket.on('join-session', ({ sessionId }: { sessionId: string }) => {
      if (sessionId) {
        const sessionRoom = `session-${sessionId}`;
        socket.join(sessionRoom);
        console.log(`Socket ${socket.id} joined room ${sessionRoom}`);
        // You can optionally send a confirmation back to the client
        socket.emit('session-joined', { sessionId });
      }
    });

    // Handle the start of a test execution
    socket.on('start-test', (payload: StartTestPayload) => {
      const { sessionId, scenarios, url } = payload;
      console.log(`Received start-test event for session: ${sessionId}`);

      // Validate payload
      if (!sessionId || !scenarios || !url) {
        socket.emit('test-failed', { error: 'Invalid payload for start-test event.' });
        return;
      }

      // Start the test execution in the background
      // The executeTests function will handle emitting progress back to the client
      executeTests(io, sessionId, scenarios, url);
    });

    // Handle client disconnection
    socket.on('disconnect', () => {
      console.log(`Client disconnected: ${socket.id}`);
    });
  });
};
