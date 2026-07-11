const routes = require('./routes');
function start() { return routes.dispatch('/'); }
module.exports = { start };
