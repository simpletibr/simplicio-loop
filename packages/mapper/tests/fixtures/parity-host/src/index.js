const express = require('express');
const { greet } = require('./greet');

function startServer() {
  const app = express();
  app.get('/', (req, res) => res.send(greet('parity')));
  return app;
}

module.exports = { startServer };
