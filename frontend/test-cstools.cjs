const csTools = require('cornerstone-tools');
console.log(csTools.getModule('segmentation') ? Object.keys(csTools.getModule('segmentation').setters || {}) : 'No seg module');
