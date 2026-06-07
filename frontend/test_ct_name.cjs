global.window = {
  navigator: {},
  document: { createElement: () => ({}), addEventListener: () => {} },
  addEventListener: () => {},
  localStorage: { getItem: () => null, setItem: () => {} }
};
const cornerstoneTools = require('cornerstone-tools');
const tool = new cornerstoneTools.FreehandScissorsTool();
console.log("Tool Name:", tool.name);
