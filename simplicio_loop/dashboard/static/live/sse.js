// Server-sent events for the Simplicio Live page: an incremental line parser and a fetch stream with backoff.
const FIRST_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 10000;
const LF = String.fromCharCode(10);
const CR = String.fromCharCode(13);

function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch (error) {
    return null;
  }
}

export function createSseParser() {
  let buffer = '';
  let data = [];
  let lastId = null;
  let eventName = null;

  function handleLine(line, out) {
    if (line === '') {
      if (data.length > 0) {
        const item = { type: 'event', id: lastId, data: data.join(LF) };
        if (eventName !== null) item.name = eventName;
        out.push(item);
      }
      data = [];
      eventName = null;
      return;
    }
    if (line.charAt(0) === ':') {
      out.push({ type: 'comment', text: line.slice(1) });
      return;
    }
    const colon = line.indexOf(':');
    const name = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.charAt(0) === ' ') value = value.slice(1);
    if (name === 'data') data.push(value);
    if (name === 'id') lastId = value;
    if (name === 'event') eventName = value;
  }

  return {
    push(text) {
      buffer += text;
      const out = [];
      let start = 0;
      let index = 0;
      while (index < buffer.length) {
        const ch = buffer.charAt(index);
        if (ch !== LF && ch !== CR) {
          index += 1;
          continue;
        }
        if (ch === CR && index === buffer.length - 1) break;
        handleLine(buffer.slice(start, index), out);
        const crlf = ch === CR && buffer.charAt(index + 1) === LF;
        index += crlf ? 2 : 1;
        start = index;
      }
      buffer = buffer.slice(start);
      return out;
    },
  };
}

async function readStream(body, handlers) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = createSseParser();
  for (;;) {
    const chunk = await reader.read();
    if (chunk.done) return;
    for (const item of parser.push(decoder.decode(chunk.value, { stream: true }))) {
      if (item.type === 'comment') {
        handlers.onHeartbeat();
      } else {
        const payload = parseJson(item.data);
        if (payload === null) continue;
        if (item.name && item.name.startsWith('alert_')) handlers.onAlert(item.name, payload);
        else handlers.onEvent(payload);
      }
    }
  }
}

function pause(ms, signal) {
  return new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timer);
      if (signal) signal.removeEventListener('abort', finish);
      resolve();
    };
    const timer = setTimeout(finish, ms);
    if (signal) signal.addEventListener('abort', finish);
  });
}

export async function connectStream({ url, token, getLastSeq, onEvent, onAlert, onHeartbeat, onStatus, signal }) {
  let backoff = FIRST_BACKOFF_MS;
  while (!(signal && signal.aborted)) {
    const headers = { Accept: 'text/event-stream', Authorization: 'Bearer ' + token };
    const seq = typeof getLastSeq === 'function' ? Number(getLastSeq()) : 0;
    if (seq > 0) headers['Last-Event-ID'] = String(seq);
    let response = null;
    try {
      response = await fetch(url, { headers, signal, cache: 'no-store' });
    } catch (error) {
      response = null;
    }
    if (response && (response.status === 401 || response.status === 403)) {
      onStatus('denied');
      return;
    }
    if (response && response.ok && response.body) {
      onStatus('live');
      backoff = FIRST_BACKOFF_MS;
      try {
        await readStream(response.body, { onEvent, onAlert: onAlert || (() => {}), onHeartbeat });
      } catch (error) {
      }
    }
    if (signal && signal.aborted) return;
    onStatus('reconnecting');
    await pause(backoff, signal);
    backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
  }
}
