function dispatch(path) { return path === '/' ? renderHome() : notFound(); }
function renderHome() { return '<html>home</html>'; }
function notFound() { return '404'; }
module.exports = { dispatch };
