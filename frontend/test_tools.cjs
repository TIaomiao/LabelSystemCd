const cornerstoneTools = require('cornerstone-tools');
console.log(Object.keys(cornerstoneTools).filter(k => k.includes('Tool') || k.includes('Scissors')));
