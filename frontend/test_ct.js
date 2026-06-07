const cornerstoneTools = require('cornerstone-tools');
console.log("Modules:", Object.keys(cornerstoneTools.store.modules));
console.log("Segmentation Module:", Object.keys(cornerstoneTools.store.modules.segmentation));
console.log("Segmentation Setters:", Object.keys(cornerstoneTools.store.modules.segmentation.setters));
