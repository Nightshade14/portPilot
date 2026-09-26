'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');

const { createApp } = require('./server');

function listen(app) {
  return new Promise((resolve) => {
    const server = app.listen(0, () => resolve(server));
  });
}

function request(server, method, path, body) {
  return new Promise((resolve, reject) => {
    const { port } = server.address();
    const data = body === undefined ? null : JSON.stringify(body);
    const req = http.request(
      {
        host: '127.0.0.1',
        port,
        method,
        path,
        headers: data
          ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) }
          : {},
      },
      (res) => {
        let raw = '';
        res.on('data', (chunk) => (raw += chunk));
        res.on('end', () => {
          let json = null;
          if (raw) {
            try {
              json = JSON.parse(raw);
            } catch {
              json = raw;
            }
          }
          resolve({ status: res.statusCode, body: json });
        });
      },
    );
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

test('health check', async (t) => {
  const app = createApp();
  const server = await listen(app);
  t.after(() => server.close());

  const res = await request(server, 'GET', '/health');
  assert.equal(res.status, 200);
  assert.deepEqual(res.body, { ok: true });
});

test('create and list bookmark', async (t) => {
  const app = createApp();
  const server = await listen(app);
  t.after(() => server.close());

  const created = await request(server, 'POST', '/bookmarks', { url: 'https://example.com' });
  assert.equal(created.status, 201);
  assert.equal(created.body.url, 'https://example.com');

  const listed = await request(server, 'GET', '/bookmarks');
  assert.equal(listed.status, 200);
  assert.equal(listed.body.bookmarks.length, 1);
});

test('create bookmark rejects missing url', async (t) => {
  const app = createApp();
  const server = await listen(app);
  t.after(() => server.close());

  const res = await request(server, 'POST', '/bookmarks', {});
  assert.equal(res.status, 400);
});

test('delete bookmark', async (t) => {
  const app = createApp();
  const server = await listen(app);
  t.after(() => server.close());

  const created = await request(server, 'POST', '/bookmarks', { url: 'https://a.com' });
  const del = await request(server, 'DELETE', `/bookmarks/${created.body.id}`);
  assert.equal(del.status, 204);

  const listed = await request(server, 'GET', '/bookmarks');
  assert.equal(listed.body.bookmarks.length, 0);
});

test('delete missing bookmark returns 404', async (t) => {
  const app = createApp();
  const server = await listen(app);
  t.after(() => server.close());

  const res = await request(server, 'DELETE', '/bookmarks/9999');
  assert.equal(res.status, 404);
});
