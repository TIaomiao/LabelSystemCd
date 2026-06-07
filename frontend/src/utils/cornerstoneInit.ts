import dicomParser from 'dicom-parser';
import cornerstone from 'cornerstone-core';
import cornerstoneWADOImageLoader from 'cornerstone-wado-image-loader';
import cornerstoneMath from 'cornerstone-math';
import cornerstoneTools from 'cornerstone-tools';
import Hammer from 'hammerjs';

let __initialized = false;

export default function initCornerstone() {
  if (__initialized) return;
  // External dependencies
  cornerstoneWADOImageLoader.external.cornerstone = cornerstone;
  cornerstoneWADOImageLoader.external.dicomParser = dicomParser;
  cornerstoneTools.external.cornerstone = cornerstone;
  cornerstoneTools.external.cornerstoneMath = cornerstoneMath;
  cornerstoneTools.external.Hammer = Hammer;

  // Initialize tools
  cornerstoneTools.init({
    showSVGCursors: true,
  });
  
  // Register tools globally
  cornerstoneTools.addTool(cornerstoneTools.WwwcTool);
  cornerstoneTools.addTool(cornerstoneTools.ZoomTool);
  cornerstoneTools.addTool(cornerstoneTools.PanTool);
  cornerstoneTools.addTool(cornerstoneTools.StackScrollMouseWheelTool);
  cornerstoneTools.addTool(cornerstoneTools.ZoomMouseWheelTool);
  cornerstoneTools.addTool(cornerstoneTools.StackScrollTool);
  cornerstoneTools.addTool(cornerstoneTools.LengthTool);
  cornerstoneTools.addTool(cornerstoneTools.FreehandRoiTool);
  cornerstoneTools.addTool(cornerstoneTools.FreehandRoiSculptorTool, {
      configuration: {
          showCursorOnHover: true,
          hoverCursor: true,
          minSpacing: 1
      }
  });


  cornerstoneTools.addTool(cornerstoneTools.BrushTool);
  cornerstoneTools.addTool(cornerstoneTools.CircleScissorsTool);
  cornerstoneTools.addTool(cornerstoneTools.FreehandScissorsTool);
  cornerstoneTools.addTool(cornerstoneTools.RectangleScissorsTool);

  // Configure Global Tool Styles & Modules
  cornerstoneTools.toolStyle.setToolWidth(2);

  // Set specific styles for FreehandRoi - Force fill configuration
  const freehandModule = cornerstoneTools.getModule('freehand');
  if (freehandModule) {
      freehandModule.configuration.alwaysShowHandles = false;
      freehandModule.configuration.invalidColor = '#ff0000';
      freehandModule.configuration.fillAlpha = 0.3;
      freehandModule.configuration.renderFill = true;
  }

  // Configure Web Workers
  const config = {
    maxWebWorkers: navigator.hardwareConcurrency || 1,
    startWebWorkersOnDemand: true,
    taskConfiguration: {
      decodeTask: {
        initializeCodecsOnStartup: false,
        usePDFJS: false,
        strict: false,
      },
    },
    webWorkerPath: '/cwil/index.worker.min.worker.js',
  };
  
  cornerstoneWADOImageLoader.webWorkerManager.initialize(config);

  // Configure Image Loader
  cornerstoneWADOImageLoader.configure({
    beforeSend: function() {
      // Add custom headers here (e.g. auth tokens)
    }
  });
  
  __initialized = true;
}
