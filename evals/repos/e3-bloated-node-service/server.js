'use strict';

const express = require('express');

function createApp() {
  const app = express();
  app.use(express.json());

  const bookmarks = new Map();
  let nextId = 1;

  app.get('/health', (req, res) => {
    res.json({ ok: true });
  });

  app.post('/bookmarks', (req, res) => {
    const { url } = req.body || {};
    if (typeof url !== 'string' || url.trim() === '') {
      return res.status(400).json({ error: 'url (string) is required' });
    }
    const id = nextId++;
    const bookmark = { id, url: url.trim() };
    bookmarks.set(id, bookmark);
    return res.status(201).json(bookmark);
  });

  app.get('/bookmarks', (req, res) => {
    res.json({ bookmarks: Array.from(bookmarks.values()) });
  });

  app.delete('/bookmarks/:id', (req, res) => {
    const id = Number(req.params.id);
    if (!bookmarks.has(id)) {
      return res.status(404).json({ error: 'not found' });
    }
    bookmarks.delete(id);
    return res.status(204).send();
  });

  return app;
}

module.exports = { createApp };

if (require.main === module) {
  const app = createApp();
  const port = process.env.PORT || 8080;
  app.listen(port, () => {
    console.log(`listening on ${port}`);
  });
}
