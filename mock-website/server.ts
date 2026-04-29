import express from 'express';
import path from 'path';

const app = express();
const PORT = 3001;

// Serve static files from /data (mounted volume in Docker)
// Falls back to mock_server/data for local dev
const dataDir = process.env.DATA_DIR
  ? path.resolve(process.env.DATA_DIR)
  : path.join(process.cwd(), 'mock_server', 'data');

app.use(express.static(dataDir, { index: 'index.html' }));

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Mock website running on http://0.0.0.0:${PORT}`);
  console.log(`Serving files from: ${dataDir}`);
});
