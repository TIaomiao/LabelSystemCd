import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';


const sourcePath = fileURLToPath(
  new URL('../legacy-runtime/assets/index-CVIBatchClear.pause-progress.js', import.meta.url)
);
export const outputPath = fileURLToPath(
  new URL('../legacy-runtime/assets/index-CVIBatchClear.repro-fix-v2.js', import.meta.url)
);

const replaceOnce = (source, search, replacement, label) => {
  const first = source.indexOf(search);
  if (first < 0) throw new Error(`Legacy runtime patch target not found: ${label}`);
  if (source.indexOf(search, first + search.length) >= 0) {
    throw new Error(`Legacy runtime patch target is ambiguous: ${label}`);
  }
  return source.slice(0, first) + replacement + source.slice(first + search.length);
};

export const patchLegacyRuntime = (input) => {
  let runtime = input;

  runtime = replaceOnce(
    runtime,
    'return(xt=K==null?void 0:K.points)!=null&&xt.length?[{key:N,renderKey:N+"-"+ue,contour:K}]:[]})}const z=(V=e.frame)==null?void 0:V[N];return z&&z.points&&z.points.length?[{key:N,renderKey:N,contour:z}]:[]}):[]',
    'return(xt=K==null?void 0:K.points)!=null&&xt.length?[{key:N,renderKey:N+"-"+ue,actionKey:N+"-"+ue,contour:K}]:[]})}const z=(V=e.frame)==null?void 0:V[N];return z&&z.points&&z.points.length?[{key:N,renderKey:N,actionKey:N,contour:z}]:[]}):[]',
    'stable action identity for rendered contours'
  );
  runtime = replaceOnce(
    runtime,
    'On.map(({key:N,renderKey:sr,contour:z})=>{',
    'On.map(({key:N,renderKey:sr,actionKey:ar,contour:z})=>{',
    'rendered contour action key destructuring'
  );
  runtime = replaceOnce(runtime, 'p({contourKey:N,anchor:ue,lastX:K.clientX,lastY:K.clientY})', 'p({contourKey:ar,anchor:ue,lastX:K.clientX,lastY:K.clientY})', 'deform action identity');
  runtime = replaceOnce(runtime, 'const dt=e.onBeginLineAdjust(N,ue);', 'const dt=e.onBeginLineAdjust(ar,ue);', 'line-adjust action identity');
  runtime = replaceOnce(runtime, 'm({contourKey:N,lastX:K.clientX,lastY:K.clientY})', 'm({contourKey:ar,lastX:K.clientX,lastY:K.clientY})', 'translate action identity');
  runtime = replaceOnce(runtime, 'window.confirm("删除当前轮廓？")&&e.onClearContour(N)', 'window.confirm("删除当前轮廓？")&&e.onClearContour(ar)', 'clear action identity');
  runtime = replaceOnce(runtime, 'U==="edit"?(o&&o.contourKey===N?[o.pointIndex]:[]):V', 'U==="edit"?(o&&o.contourKey===ar?[o.pointIndex]:[]):V', 'active handle action identity');
  runtime = replaceOnce(runtime, 'i({contourKey:N,pointIndex:K})}},`${N}-${K}`)', 'i({contourKey:ar,pointIndex:K})}},`${ar}-${K}`)', 'point action identity');

  runtime = replaceOnce(
    runtime,
    'function Fp(d,x,E){',
    'function __cviParseContourActionKey(d){const x=/^exclude-(\\d+)$/.exec(String(d));return x?{key:"exclude",regionIndex:Number(x[1])}:{key:d,regionIndex:null}}function __cviGetFrameContour(d,x){const E=__cviParseContourActionKey(x);return E.key==="exclude"&&E.regionIndex!==null?Array.isArray(d==null?void 0:d.exclude_regions)?d.exclude_regions[E.regionIndex]??null:null:d==null?void 0:d[E.key]}function __cviActionFrameProxy(d){return new Proxy(d,{get(x,E){if(typeof E==="string"&&E.startsWith("exclude-"))return __cviGetFrameContour(x,E);return x[E]}})}function __cviApplyActionFrame(d){if(!d||typeof d!=="object")return d;const x=Object.keys(d).filter(E=>/^exclude-\\d+$/.test(E));if(!x.length)return d;const E={...d},_=Array.isArray(E.exclude_regions)?E.exclude_regions.slice():E.exclude?[E.exclude]:[];for(const R of x){const X=__cviParseContourActionKey(R),oe=E[R];delete E[R];if(X.regionIndex===null||X.regionIndex<0||X.regionIndex>=_.length)continue;oe&&Array.isArray(oe.points)&&oe.points.length?_[X.regionIndex]=oe:_.splice(X.regionIndex,1)}E.exclude_regions=_,E.exclude=_[_.length-1]??null;return E}function __cviRecordAction(d,x={}){const E=window.__cviActionTrace??(window.__cviActionTrace=[]);E.push({type:d,at:new Date().toISOString(),...x}),E.length>20&&E.splice(0,E.length-20)}function Fp(d,x,E){',
    'exclude action-key adapter helpers'
  );
  runtime = replaceOnce(
    runtime,
    'const E=bx(d(x.frames[br]??{include:!0}),j.cols,j.rows);',
    'const E=bx(__cviApplyActionFrame(d(__cviActionFrameProxy(x.frames[br]??{include:!0}))),j.cols,j.rows);',
    'apply stable exclude-region edits before frame normalization'
  );
  runtime = replaceOnce(
    runtime,
    'R=_==null?void 0:_[d];return R!=null&&R.points&&R.points.length?',
    'R=__cviGetFrameContour(_,d);return R!=null&&R.points&&R.points.length?',
    'line-adjust reads the selected exclude region'
  );
  runtime = replaceOnce(
    runtime,
    'const E=d==="exclude"?null:(b==null?void 0:b.frames[br])?.[d]?.points??null,_=__cviReplaceStrokeSegment(E,x,j.cols,j.rows);',
    'const E=d==="exclude"?null:__cviGetFrameContour(b==null?void 0:b.frames[br],d)?.points??null,_=__cviReplaceStrokeSegment(E,x,j.cols,j.rows);',
    'freehand correction reads the selected exclude region'
  );

  runtime = replaceOnce(
    runtime,
    'async function __flushContourAutoSave(d){const x=__cviContourAutoSaveState[d];',
    'async function __flushContourAutoSave(d){const x=__cviContourAutoSaveState[d];',
    'autosave function anchor'
  );
  runtime = replaceOnce(
    runtime,
    'x.running=!1,x.nextTask&&__flushContourAutoSave(d)}function __queueContourAutoSave',
    'x.running=!1,x.nextTask&&__flushContourAutoSave(d)}async function __waitForContourAutoSave(d){const x=__cviContourAutoSaveState[d];if(!x)return;const E=Date.now()+45e3;for(;;){x.nextTask&&!x.running&&__flushContourAutoSave(d);if(!x.running&&!x.nextTask)return;if(Date.now()>E)throw new Error("轮廓保存等待超时，请复制诊断信息后重试。");await new Promise(_=>window.setTimeout(_,25))}}function __queueContourAutoSave',
    'awaitable autosave drain'
  );
  runtime = replaceOnce(
    runtime,
    'R.nextTask={module:d,seriesId:x,payload:E},window.__cviLastContourAutoSaveKey=_,R.timer&&window.clearTimeout(R.timer),R.timer=null,__flushContourAutoSave(_)}window.__cviFlushContourAutoSaveByKey=__flushContourAutoSave,window.__cviFlushContourAutoSave=(d,x)=>d&&x?__flushContourAutoSave(`${d}:${x}`):Promise.resolve()',
    'R.nextTask={module:d,seriesId:x,payload:E},window.__cviLastContourAutoSaveKey=_,R.timer&&window.clearTimeout(R.timer),R.timer=null,__cviRecordAction("autosave_queued",{module:d,series_id:x}),__flushContourAutoSave(_)}window.__cviFlushContourAutoSaveByKey=__waitForContourAutoSave,window.__cviFlushContourAutoSave=(d,x)=>d&&x?__waitForContourAutoSave(`${d}:${x}`):Promise.resolve()',
    'public autosave flush waits for in-flight saves'
  );
  runtime = runtime.replaceAll('await __flushContourAutoSave(`', 'await __waitForContourAutoSave(`');

  runtime = replaceOnce(
    runtime,
    'async function Vu(){if(!T||!j||!b)return;const d=await le.saveContours(j.id,b);hn(T,j.id,d,{recordHistory:!1})}',
    'async function Vu(){if(!T||!j||!b)return;Bi("正在保存最新轮廓...");__cviRecordAction("manual_save_start",{module:T,series_id:j.id});try{await __waitForContourAutoSave(`${T}:${j.id}`);const d=await le.saveContours(j.id,b);hn(T,j.id,d,{recordHistory:!1}),Bi(`轮廓已保存（${new Date().toLocaleTimeString()}）`),__cviRecordAction("manual_save_ok",{module:T,series_id:j.id})}catch(d){Bi(d instanceof Error?d.message:"轮廓保存失败。"),__cviRecordAction("manual_save_failed",{module:T,series_id:j.id})}}async function __cviRecomputeCurrent(){if(!T||!j||!b)return;Bi("正在保存最新轮廓并重算指标...");__cviRecordAction("recompute_start",{module:T,series_id:j.id});try{await __waitForContourAutoSave(`${T}:${j.id}`);const d=await le.saveContours(j.id,b);hn(T,j.id,d,{recordHistory:!1});const x=T==="function"?await le.recomputeFunction(j.id):await le.recomputeLge(j.id,h,g,v);gn.setState(E=>({measurements:{...E.measurements,[T]:x},study:zx(E.study,T,x),error:null})),window.__cviLastRecomputeStatus={status:"ok",module:T,series_id:j.id,at:new Date().toISOString()},Bi(`指标已按最新轮廓重算（${new Date().toLocaleTimeString()}）`),__cviRecordAction("recompute_ok",{module:T,series_id:j.id})}catch(d){window.__cviLastRecomputeStatus={status:"failed",module:T,series_id:j.id,at:new Date().toISOString()},Bi(d instanceof Error?d.message:"指标重算失败。"),__cviRecordAction("recompute_failed",{module:T,series_id:j.id})}}',
    'deterministic save and recompute workflow'
  );
  runtime = replaceOnce(runtime, 'onClick:()=>void G(T),disabled:ke,children:"重算指标"', 'onClick:()=>void __cviRecomputeCurrent(),disabled:ke,children:"重算指标"', 'recompute button waits for latest contours');

  runtime = replaceOnce(
    runtime,
    'if(N.button===2){zn(N,"window");return}',
    'if(N.button===2||N.button===0&&N.ctrlKey&&/Mac|iPhone|iPad/.test(navigator.platform)){zn(N,"window");return}',
    'macOS control-click window-level gesture'
  );

  runtime = replaceOnce(
    runtime,
    'Zr=Yx(b==null?void 0:b.source),__pp=__cviPropagationSettings(b);',
    'Zr=Yx(b==null?void 0:b.source),__pp=__cviPropagationSettings(b);window.__cviBuildDiagnosticSnapshot=()=>{const d=He?__cviContourAutoSaveState[He]:null,x=Array.isArray(Zt==null?void 0:Zt.exclude_regions)?Zt.exclude_regions.length:(Zt==null?void 0:Zt.exclude)?1:0;return{workstation_version:(Array.from(document.querySelectorAll("span,div")).map(E=>(E.textContent||"").trim()).find(E=>/^v\\d{4}\\.\\d{2}\\.\\d{2}/.test(E))||null),runtime_version:"2026.08.15-repro-fix-2",browser:navigator.userAgent,platform:navigator.platform,viewport:{width:window.innerWidth,height:window.innerHeight,device_pixel_ratio:window.devicePixelRatio},study_id:(o==null?void 0:o.id)??null,series_id:(j==null?void 0:j.id)??null,module:T??null,series_role:(j==null?void 0:j.role)??null,slice_index:_e,phase_index:ce,frame_key:br,tool_mode:Ie,contour_tool_mode:Se,selected_contour:c,exclude_region_count:x,autosave:{running:!!(d!=null&&d.running),pending:!!(d!=null&&d.nextTask)},latest_measurement_available:!!O,last_recompute_status:window.__cviLastRecomputeStatus??null,recent_actions:(window.__cviActionTrace??[]).slice(-20)}};async function __cviCopyDiagnostics(){const d=["CMR 问题反馈","发生前操作：","预期结果：","实际结果：","是否刷新/换电脑：","诊断信息：",JSON.stringify(window.__cviBuildDiagnosticSnapshot(),null,2)].join("\\n");try{await navigator.clipboard.writeText(d),Bi("诊断信息已复制，可直接粘贴到反馈群。"),__cviRecordAction("diagnostics_copied",{module:T,series_id:(j==null?void 0:j.id)??null})}catch{window.prompt("请复制以下诊断信息：",d)}}',
    'privacy-safe diagnostic snapshot and feedback template'
  );
  runtime = replaceOnce(
    runtime,
    'a.jsx("button",{className:"ghost-button",onClick:()=>void __cviRecomputeCurrent(),disabled:ke,children:"重算指标"})]}),',
    'a.jsx("button",{className:"ghost-button",onClick:()=>void __cviRecomputeCurrent(),disabled:ke,children:"重算指标"}),a.jsx("button",{className:"ghost-button",onClick:()=>void __cviCopyDiagnostics(),children:"复制诊断信息"})]}),',
    'diagnostic feedback button'
  );

  return runtime;
};

const source = readFileSync(sourcePath, 'utf8');
const patched = patchLegacyRuntime(source);
writeFileSync(outputPath, patched);
console.log(`Generated patched legacy runtime: ${outputPath}`);
