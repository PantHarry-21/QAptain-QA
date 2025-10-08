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
    socket.on('join-session', async ({ sessionId }: { sessionId: string }) => {
      if (sessionId) {
        const sessionRoom = `session-${sessionId}`;
        socket.join(sessionRoom);
        console.log(`Socket ${socket.id} joined room ${sessionRoom}`);
        
        // Fetch initial data and send to the client
        try {
          const apiUrl = `${process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000'}/api/results/${sessionId}`;
          const response = await fetch(apiUrl);
          if (response.ok) {
            const { data } = await response.json();
            socket.emit('session-data', data);
          } else {
            console.error(`Failed to fetch initial session data for ${sessionId}:`, await response.text());
          }
        } catch (error) {
          console.error(`Error fetching initial session data for ${sessionId}:`, error);
        }
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
