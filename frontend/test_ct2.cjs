global.window = {
  navigator: {},
  document: {
    createElement: () => ({}),
    addEventListener: () => {}
  },
  addEventListener: () => {}
};
const cornerstoneTools = require('cornerstone-tools');
console.log("FreehandScissorsTool:", !!cornerstoneTools.FreehandScissorsTool);
console.log("FreehandRoiTool:", !!cornerstoneTools.FreehandRoiTool);
console.log("BrushTool:", !!cornerstoneTools.BrushTool);
