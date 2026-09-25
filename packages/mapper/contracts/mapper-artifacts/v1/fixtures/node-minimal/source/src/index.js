"use strict";

function greet(name) {
  return `Hello, ${name}!`;
}

function main() {
  console.log(greet("world"));
}

if (require.main === module) {
  main();
}

module.exports = { greet, main };
