const csTools = require('cornerstone-tools');
const seg = csTools.getModule('segmentation');
console.log(Object.keys(seg.setters || {}));
