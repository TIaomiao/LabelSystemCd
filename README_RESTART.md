# LabelSystem 启动与维护指南

## 1. 快速启动

### 后端 (Flask)
确保已安装 Conda 并且环境 `label_sys` 已配置：
```bash
# 进入项目根目录
conda run -n label_sys python backend/app.py
```
后端默认运行在 `http://localhost:5000`。

### 前端 (Vite + React)
确保已激活 `label_sys` 环境（包含 nodejs）：
```bash
# 激活环境
conda activate label_sys

# 进入前端目录
cd frontend

# 启动开发服务器
npm run dev
```
前端默认运行在 `http://localhost:5173`。

---

## 2. 现有功能说明
- **DICOM 浏览**：支持窗宽窗位（Levels）、平移（Pan）、缩放（Zoom）、滚轮翻页（Scroll）。
- **标注系统**：
    - 支持 **部位预设**（左心室、右心室、心肌、主动脉）。
    - **独立颜色**：不同部位标注拥有独立持久颜色，切换部位不影响旧标注。
    - **右键取消**：在绘制过程中或选中标注时，点击右键可删除当前标注。
    - **透明填充 (待完善)**：逻辑已注入，但部分环境下 Mask 渲染仍存在问题。

---

## 3. 遗留问题与修复建议

### 问题：FreehandRoi (自由画线) Mask 填充失效
**当前状态**：
代码中已在以下维度注入填充逻辑：
1. `cornerstoneTools.getModule('freehand').configuration` 设置了 `renderFill: true`。
2. `addToolForElement` 实例配置中注入了 `fillAlpha: 0.3`。
3. `onMeasurementAdded` 事件中为每个数据点强制注入了 `renderFill` 属性。

**修复建议**：
1. **渲染器冲突**：检查 `cornerstone-tools` 是否正在使用 SVG 渲染器。SVG 渲染器有时对 `fill` 属性的支持需要显式的 CSS 或特定的属性路径。
2. **闭合检查**：FreehandRoi 必须在**完全闭合**（点击起点）后才会触发填充。可以尝试在 `onMeasurementAdded` 后手动调用 `cornerstone.updateImage(element)`。
3. **版本兼容性**：如果使用的是较新版本的 `cornerstone-tools`，部分配置可能已迁移到 `toolStyles` 或特定的 `drawing` 模块。建议检查 `cornerstone-tools` 源码中 `freehand/renderToolData.js` 的填充实现逻辑。

---

## 4. 关键文件索引
- **前端核心逻辑**：[DicomViewer.tsx](frontend/src/components/DicomViewer.tsx)
- **Cornerstone 初始化**：[cornerstoneInit.ts](frontend/src/utils/cornerstoneInit.ts)
- **后端入口**：[app.py](backend/app.py)
