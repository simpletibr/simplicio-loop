const { handle } = require('./consumer');
function publish(event) { return handle(event); }
module.exports = { publish };
