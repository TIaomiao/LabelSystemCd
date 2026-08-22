(function () {
  if (!document.documentElement.classList.contains('cvi-embedded')) return;

  const EMBEDDED_VERSION = 'v2026.08.13-2';
  const CVI_API_BASE = '/cvi-api';
  const storage = window.localStorage;
  const keys = {
    left: 'cvi.embedded.leftColumn',
    right: 'cvi.embedded.rightColumn',
    reference: 'cvi.embedded.referenceColumnPercent',
    autoEdEs: 'cvi.embedded.autoEdEs.'
  };

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const readNumber = (key, fallback) => {
    const raw = storage.getItem(key);
    const value = raw == null ? NaN : Number(raw);
    return Number.isFinite(value) ? value : fallback;
  };

  const seriesCache = {
    studyId: null,
    series: [],
    pendingStudyId: null
  };

  const normalizeSeries = (series) => {
    if (!series || typeof series !== 'object') return null;
    const id = Number(series.id);
    if (!Number.isFinite(id)) return null;
    return {
      ...series,
      id,
      description: String(series.description || ''),
      role: String(series.role || 'unknown'),
      is_tissue_lge_primary: series.is_tissue_lge_primary === true
    };
  };

  const captureStudyPayload = (payload) => {
    if (!payload || typeof payload !== 'object' || !Array.isArray(payload.series)) return;
    const studyId = Number(payload.id);
    const normalized = payload.series.map(normalizeSeries).filter(Boolean);
    if (!Number.isFinite(studyId) || !normalized.length) return;
    seriesCache.studyId = studyId;
    seriesCache.series = normalized;
    seriesCache.pendingStudyId = null;
    window.__cviSeriesCache = {
      studyId,
      series: normalized
    };
    window.dispatchEvent(new CustomEvent('cvi:series-cache-updated', {
      detail: { studyId, seriesCount: normalized.length }
    }));
  };

  const getStudyIdFromUrl = (url) => {
    try {
      const parsed = new URL(String(url), window.location.origin);
      const match = parsed.pathname.match(/\/studies\/(\d+)$/);
      return match ? Number(match[1]) : null;
    } catch {
      return null;
    }
  };

  const getCurrentStudyId = () => {
    const match = window.location.pathname.match(/\/study\/(\d+)(?:\/|$)/);
    return match ? Number(match[1]) : null;
  };

  const readNavigatorIndex = (labelText) => {
    const labels = Array.from(document.querySelectorAll('.navigator-bar label'));
    const matchedLabel = labels.find((label) => {
      const labelNode = Array.from(label.childNodes).find((node) => node.nodeType === Node.TEXT_NODE);
      const text = (labelNode?.textContent || label.textContent || '').trim();
      return text.startsWith(labelText);
    });
    const value = Number(matchedLabel?.querySelector('input[type="range"]')?.value || 0);
    return Number.isFinite(value) ? Math.max(0, Math.trunc(value)) : 0;
  };

  const captureMeasurementPayload = (payload) => {
    if (!payload || typeof payload !== 'object') return;
    if (!payload.metrics || !payload.research) return;
    window.__cviMeasurementPayload = payload;
    window.__cviMeasurementPayloadBySeries = window.__cviMeasurementPayloadBySeries || {};
    if (payload.series_id != null) {
      window.__cviMeasurementPayloadBySeries[String(payload.series_id)] = payload;
    }
    window.dispatchEvent(new CustomEvent('cvi:measurements-updated', {
      detail: {
        module: payload.module || '',
        seriesId: payload.series_id || null
      }
    }));
  };

  const patchFetchForSeriesCache = () => {
    if (window.__cviSeriesCacheFetchPatched === '1' || typeof window.fetch !== 'function') return;
    window.__cviSeriesCacheFetchPatched = '1';
    const originalFetch = window.fetch.bind(window);
    window.fetch = (...args) => {
      let requestUrl = args[0] instanceof Request ? args[0].url : args[0];
      let requestArgs = args;
      const requestMethod = String(args[1]?.method || (args[0] instanceof Request ? args[0].method : 'GET')).toUpperCase();
      const excludeActive = Array.from(document.querySelectorAll('.tool-pills button')).some((button) => (
        button.classList.contains('is-active') && button.textContent?.trim() === '排除区'
      ));
      if (typeof args[0] === 'string' && requestMethod === 'PUT' && excludeActive) {
        try {
          const parsed = new URL(String(requestUrl), window.location.origin);
          if (/\/contours\/\d+$/.test(parsed.pathname) && !parsed.searchParams.has('recompute')) {
            parsed.searchParams.set('recompute', 'false');
            requestUrl = parsed.origin === window.location.origin
              ? `${parsed.pathname}${parsed.search}${parsed.hash}`
              : parsed.toString();
            requestArgs = [requestUrl, args[1]];
          }
        } catch {}
      }
      if (typeof args[0] === 'string' && requestMethod === 'POST') {
        try {
          const parsed = new URL(String(requestUrl), window.location.origin);
          if (/\/measurements\/lge$/.test(parsed.pathname) && typeof args[1]?.body === 'string') {
            const payload = JSON.parse(args[1].body);
            payload.phase_index = readNavigatorIndex('Phase');
            requestArgs = [requestUrl, { ...args[1], body: JSON.stringify(payload) }];
          }
        } catch {}
      }
      const studyId = getStudyIdFromUrl(requestUrl);
      return originalFetch(...requestArgs).then((response) => {
        if (studyId && response.ok) {
          response.clone().json().then(captureStudyPayload).catch(() => {});
        }
        if (response.ok) {
          response.clone().json().then(captureMeasurementPayload).catch(() => {});
        }
        return response;
      });
    };
  };

  patchFetchForSeriesCache();

  const refreshCurrentStudySeriesCache = () => {
    const studyId = getCurrentStudyId();
    if (!studyId || seriesCache.studyId === studyId || seriesCache.pendingStudyId === studyId) return;
    seriesCache.pendingStudyId = studyId;
    window.fetch(`${CVI_API_BASE}/studies/${studyId}`, { headers: { Accept: 'application/json' } })
      .then((response) => response.ok ? response.json() : null)
      .then(captureStudyPayload)
      .catch(() => {
        if (seriesCache.pendingStudyId === studyId) seriesCache.pendingStudyId = null;
      });
  };

  const setRootVars = () => {
    document.documentElement.style.setProperty('--cvi-left-col', `${readNumber(keys.left, 300)}px`);
    document.documentElement.style.setProperty('--cvi-right-col', `${readNumber(keys.right, 360)}px`);
    document.documentElement.style.setProperty('--cvi-reference-col', `${readNumber(keys.reference, 31)}%`);
  };

  const ensureWorkspaceHandles = () => {
    const grid = document.querySelector('.workspace-grid');
    if (!grid || grid.dataset.cviResizable === '1') return;
    grid.dataset.cviResizable = '1';

    const leftHandle = document.createElement('div');
    leftHandle.className = 'cvi-grid-resizer is-left';
    leftHandle.title = '拖动调整病例/协议栏宽度';

    const rightHandle = document.createElement('div');
    rightHandle.className = 'cvi-grid-resizer is-right';
    rightHandle.title = '拖动调整右侧工具栏宽度';

    grid.append(leftHandle, rightHandle);

    const updateHandlePositions = () => {
      const rect = grid.getBoundingClientRect();
      const left = readNumber(keys.left, 300);
      const right = readNumber(keys.right, 360);
      leftHandle.style.left = `${left}px`;
      rightHandle.style.left = `${rect.width - right}px`;
    };

    const startDrag = (event, side) => {
      event.preventDefault();
      document.body.classList.add('cvi-is-resizing');

      const move = (moveEvent) => {
        const rect = grid.getBoundingClientRect();
        if (side === 'left') {
          const maxLeft = Math.max(220, Math.min(520, rect.width - 660));
          const next = clamp(moveEvent.clientX - rect.left, 220, maxLeft);
          storage.setItem(keys.left, String(Math.round(next)));
        } else {
          const maxRight = Math.max(280, Math.min(560, rect.width - 620));
          const next = clamp(rect.right - moveEvent.clientX, 280, maxRight);
          storage.setItem(keys.right, String(Math.round(next)));
        }
        setRootVars();
        updateHandlePositions();
      };

      const stop = () => {
        document.body.classList.remove('cvi-is-resizing');
        window.removeEventListener('mousemove', move);
        window.removeEventListener('mouseup', stop);
      };

      window.addEventListener('mousemove', move);
      window.addEventListener('mouseup', stop);
    };

    leftHandle.addEventListener('mousedown', (event) => startDrag(event, 'left'));
    rightHandle.addEventListener('mousedown', (event) => startDrag(event, 'right'));
    window.addEventListener('resize', updateHandlePositions);
    updateHandlePositions();
  };

  const ensureViewerHandles = () => {
    document.querySelectorAll('.viewer-grid').forEach((grid) => {
      if (grid.dataset.cviViewerResizable === '1') return;
      grid.dataset.cviViewerResizable = '1';

      const handle = document.createElement('div');
      handle.className = 'cvi-viewer-resizer';
      handle.title = '拖动调整主视图和参考视图宽度';
      grid.appendChild(handle);

      const updateHandlePosition = () => {
        const rect = grid.getBoundingClientRect();
        const pct = readNumber(keys.reference, 34);
        handle.style.left = `${rect.width * (1 - pct / 100)}px`;
      };

      const startDrag = (event) => {
        event.preventDefault();
        document.body.classList.add('cvi-is-resizing');

        const move = (moveEvent) => {
          const rect = grid.getBoundingClientRect();
          const pct = clamp(((rect.right - moveEvent.clientX) / rect.width) * 100, 24, 50);
          storage.setItem(keys.reference, String(Math.round(pct)));
          setRootVars();
          updateHandlePosition();
        };

        const stop = () => {
          document.body.classList.remove('cvi-is-resizing');
          window.removeEventListener('mousemove', move);
          window.removeEventListener('mouseup', stop);
        };

        window.addEventListener('mousemove', move);
        window.addEventListener('mouseup', stop);
      };

      handle.addEventListener('mousedown', startDrag);
      window.addEventListener('resize', updateHandlePosition);
      updateHandlePosition();
    });
  };

  const findAuxiliarySource = () => {
    const sections = Array.from(document.querySelectorAll('.inspector .panel-section'));
    return sections.find((section) => {
      const title = section.querySelector('strong')?.textContent?.trim() || '';
      return title === 'Volume Curve' || title === 'Polar Map';
    }) || null;
  };

  const updateReferenceAuxiliary = (stack) => {
    let auxiliary = stack.querySelector('.cvi-reference-aux');
    if (!auxiliary) {
      auxiliary = document.createElement('section');
      auxiliary.className = 'cvi-reference-aux';
      stack.appendChild(auxiliary);
    }

    const source = findAuxiliarySource();
    if (source) {
      source.classList.add('cvi-aux-source-hidden');
      const title = source.querySelector('strong')?.textContent?.trim() || 'Supplement';
      const hash = source.textContent || '';
      if (auxiliary.dataset.sourceHash !== hash) {
        auxiliary.dataset.sourceHash = hash;
        auxiliary.innerHTML = '';
        const clone = source.cloneNode(true);
        clone.classList.remove('panel-section', 'cvi-aux-source-hidden');
        clone.classList.add('cvi-reference-aux-card');
        auxiliary.appendChild(clone);
      }
      auxiliary.dataset.title = title;
      return;
    }

    if (auxiliary.dataset.sourceHash !== 'placeholder') {
      auxiliary.dataset.sourceHash = 'placeholder';
      auxiliary.innerHTML = [
        '<div class="cvi-reference-placeholder">',
        '<strong>补充视图</strong>',
        '<span>这里会放 Volume Curve、LGE 定量图或后续补充图。</span>',
        '</div>'
      ].join('');
    }
  };

  const ensure4chRoleWarning = () => {
    const center = document.querySelector('.center-pane');
    if (!center) return;

    const mainTitle = center.querySelector('.viewer-grid > .viewer-card:first-child .viewer-head h3')?.textContent?.trim() || '';
    const mainSubtitle = center.querySelector('.viewer-grid > .viewer-card:first-child .viewer-head p')?.textContent?.trim() || '';
    const isMissing4chMain = mainTitle === 'Cine 4CH' && mainSubtitle === '未选择序列';
    const has4chRole = (window.__cviSeriesCache?.series || []).some((series) => series?.role === 'cine_lax_4ch');

    let warning = center.querySelector('.cvi-4ch-role-warning');
    if (!isMissing4chMain || has4chRole) {
      warning?.remove();
      return;
    }

    if (!warning) {
      warning = document.createElement('div');
      warning.className = 'cvi-4ch-role-warning';
      warning.textContent = '未找到 role=cine_lax_4ch 的 4CH 序列。当前不会自动打开 SAX；请在 Series Overview 检查对应序列 role。';
      const viewerGrid = center.querySelector('.viewer-grid');
      if (viewerGrid) center.insertBefore(warning, viewerGrid);
      else center.prepend(warning);
    }
  };

  const fitViewerStages = () => {
    document.querySelectorAll('.viewer-grid > .viewer-card > .viewer-stage').forEach((stage) => {
      stage.style.removeProperty('--cvi-fit-stage-height');
      delete stage.dataset.cviFitHeight;
    });
  };

  const ensureWorkstationVersionBadge = () => {
    const candidates = Array.from(document.querySelectorAll('h1, strong, .brand-block, .brand-block *'));
    candidates.forEach((node) => {
      if (!(node instanceof HTMLElement)) return;
      const text = (node.textContent || '').trim();
      if (text !== 'CMR Workstation') return;
      const parent = node.parentElement;
      if (!parent) return;

      let badge = parent.querySelector('.cvi-version-badge');
      if (!badge) {
        badge = document.createElement('span');
        badge.className = 'cvi-version-badge';
        parent.appendChild(badge);
      }
      if (badge.textContent !== EMBEDDED_VERSION) {
        badge.textContent = EMBEDDED_VERSION;
      }
      badge.setAttribute('title', `当前工作台版本 ${EMBEDDED_VERSION}`);
    });
  };

  const findToolbarGroupByLabel = (labelText) => {
    return Array.from(document.querySelectorAll('.viewer-toolbar > .viewer-toolbar-group')).find((group) => {
      const label = group.querySelector('.viewer-toolbar-label')?.textContent?.trim() || '';
      return label === labelText;
    }) || null;
  };

  const syncContourToolControls = () => {
    const source = findToolbarGroupByLabel('Contour Tool');
    const panel = document.querySelector('.inspector .tool-attribute-panel');
    const existing = panel?.querySelector('.cvi-contour-mode-panel');

    if (!source || !panel) {
      existing?.remove();
      return;
    }

    source.classList.add('cvi-toolbar-contour-source-hidden');

    let target = existing;
    if (!target) {
      target = document.createElement('section');
      target.className = 'cvi-contour-mode-panel';
      target.innerHTML = [
        '<div class="cvi-contour-mode-title">勾画方式</div>',
        '<div class="cvi-contour-mode-buttons"></div>'
      ].join('');
    }

    const header = panel.querySelector(':scope > .tool-attribute-header');
    if (target.parentElement !== panel) {
      header?.insertAdjacentElement('afterend', target) || panel.prepend(target);
    } else if (header && target.previousElementSibling !== header) {
      header.insertAdjacentElement('afterend', target);
    }

    const buttonsHost = target.querySelector('.cvi-contour-mode-buttons');
    const sourceButtons = Array.from(source.querySelectorAll('button'));
    const signature = sourceButtons.map((sourceButton) => [
      sourceButton.textContent || '',
      sourceButton.className || '',
      sourceButton.disabled ? '1' : '0',
      sourceButton.title || ''
    ].join('|')).join('::');
    if (target.dataset.signature === signature) return;

    target.dataset.signature = signature;
    buttonsHost.innerHTML = '';
    sourceButtons.forEach((sourceButton) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = sourceButton.className;
      button.textContent = sourceButton.textContent || '';
      button.title = sourceButton.title || '';
      button.disabled = sourceButton.disabled;
      button.addEventListener('click', () => sourceButton.click());
      buttonsHost.appendChild(button);
    });
  };

  const renameContourTargetSection = () => {
    document.querySelectorAll('.inspector .tool-group > strong').forEach((title) => {
      if ((title.textContent || '').trim() === '轮廓工具') {
        title.textContent = '勾画部位';
      }
    });
  };

  const removeViewerProtocolEntry = () => {
    const items = Array.from(document.querySelectorAll('.protocol-item'));
    const viewerItem = items.find((item) => {
      if (!(item instanceof HTMLElement)) return false;
      const label = getProtocolItemLabel(item);
      const sublabel = item.querySelector('small')?.textContent?.trim() || '';
      return normalizeProtocolLabel(label) === 'viewer' || normalizeProtocolLabel(sublabel) === '影像视图';
    });
    if (!(viewerItem instanceof HTMLElement)) return;

    const wasActive = viewerItem.classList.contains('is-active');
    viewerItem.remove();

    if (!wasActive) return;
    const fallbackItem = Array.from(document.querySelectorAll('.protocol-item')).find((item) => {
      return item instanceof HTMLElement
        && normalizeProtocolLabel(getProtocolItemLabel(item)) === 'seriesoverview';
    }) || Array.from(document.querySelectorAll('.protocol-item')).find((item) => item instanceof HTMLElement);
    fallbackItem?.click();
  };

  const isSeriesOverviewVisible = () => {
    const overviewGrid = document.querySelector('.overview-grid');
    if (!overviewGrid) return false;
    const panel = overviewGrid.closest('.panel');
    const title = panel?.querySelector('.panel-title h2')?.textContent?.trim() || '';
    return title === 'Series Overview' || Boolean(panel);
  };

  const hideSeriesOverviewToolbar = () => {
    const shouldHide = isSeriesOverviewVisible();
    document.querySelectorAll('.viewer-toolbar').forEach((toolbar) => {
      toolbar.classList.toggle('cvi-series-overview-toolbar-hidden', shouldHide);
    });
  };

  const getSeriesIdFromOverviewCard = (card) => {
    const explicit = Number(card.dataset.cviSeriesId);
    if (Number.isFinite(explicit) && explicit > 0) return explicit;
    const imageSource = card.querySelector('img')?.getAttribute('src') || card.querySelector('img')?.src || '';
    const match = imageSource.match(/\/series\/(\d+)\/image(?:\?|$)/);
    return match ? Number(match[1]) : null;
  };

  const getOverviewCardSeries = (card, index) => {
    const seriesId = getSeriesIdFromOverviewCard(card);
    if (seriesId) {
      const matched = seriesCache.series.find((series) => series.id === seriesId);
      if (matched) return matched;
      return { id: seriesId, role: card.dataset.cviSeriesRole || 'unknown', description: '' };
    }

    const heading = card.querySelector('h3')?.textContent?.trim() || '';
    const exactMatches = seriesCache.series.filter((series) => series.description === heading);
    if (exactMatches.length === 1) return exactMatches[0];
    return seriesCache.series[index] || null;
  };

  const setOverviewCardRoleText = (card, role) => {
    const roleNode = card.querySelector('p');
    if (roleNode && (roleNode.textContent || '').trim() !== role) {
      roleNode.textContent = role;
    }
    card.dataset.cviSeriesRole = role;
  };

  const inferLgeRole = (series) => {
    const text = `${series?.description || ''} ${series?.role || ''}`.toLowerCase();
    return /(^|[^a-z0-9])4\s*ch([^a-z0-9]|$)|4ch|lax|long|chamber|coronal/.test(text) ? 'lge_lax' : 'lge_sax';
  };

  const overviewRoleOptions = [
    { key: 'sax', label: 'SAX', role: () => 'cine_sax' },
    { key: '2ch', label: '2CH', role: () => 'cine_lax_2ch' },
    { key: '3ch', label: '3CH', role: () => 'cine_lax_3ch' },
    { key: '4ch', label: '4CH', role: () => 'cine_lax_4ch' },
    { key: 'lge', label: 'LGE', role: inferLgeRole },
    { key: 'unknown', label: '清除', role: () => 'unknown' }
  ];

  const isRoleOptionActive = (optionKey, role) => {
    if (optionKey === 'sax') return role === 'cine_sax';
    if (optionKey === '2ch') return role === 'cine_lax_2ch';
    if (optionKey === '3ch') return role === 'cine_lax_3ch';
    if (optionKey === '4ch') return role === 'cine_lax_4ch';
    if (optionKey === 'lge') return role === 'lge_sax' || role === 'lge_lax';
    return role === 'unknown';
  };

  const resolveEffectiveTissueLgePrimary = (seriesList) => {
    const eligible = Array.isArray(seriesList)
      ? seriesList.filter((item) => item?.role === 'lge_sax')
      : [];
    const explicit = eligible.find((item) => item.is_tissue_lge_primary === true);
    const effective = explicit || eligible[0] || null;
    return {
      seriesId: effective?.id == null ? null : Number(effective.id),
      isExplicit: Boolean(explicit)
    };
  };

  const getEffectiveTissueLgePrimary = () => {
    const availableSeries = seriesCache.series.length
      ? seriesCache.series
      : Array.isArray(window.__cviSeriesCache?.series)
        ? window.__cviSeriesCache.series
        : [];
    return resolveEffectiveTissueLgePrimary(availableSeries);
  };

  const updateSeriesRoleControlsState = (card, series) => {
    const host = card.querySelector('.cvi-role-controls');
    if (!host) return;
    const role = series?.role || card.dataset.cviSeriesRole || 'unknown';
    host.dataset.currentRole = role;
    host.querySelectorAll('.cvi-role-choice').forEach((choice) => {
      if (choice.dataset.roleKey === 'tissue-lge-primary') {
        const eligible = role === 'lge_sax';
        const effectivePrimary = getEffectiveTissueLgePrimary();
        const active = eligible && Number(series?.id) === effectivePrimary.seriesId;
        const explicit = active && series?.is_tissue_lge_primary === true;
        choice.hidden = !eligible;
        choice.classList.toggle('is-active', active);
        choice.setAttribute('aria-pressed', active ? 'true' : 'false');
        choice.textContent = active ? 'Tissue LGE ✓' : '设为 Tissue LGE';
        choice.title = active
          ? explicit
            ? '当前 Tissue LGE 使用人工指定的此序列'
            : '尚未人工指定，当前按序列顺序默认使用此序列'
          : '将此 lge_sax 序列设为 Tissue LGE 的默认标注序列';
        return;
      }
      const active = isRoleOptionActive(choice.dataset.roleKey, role);
      choice.classList.toggle('is-active', active);
      choice.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    setOverviewCardRoleText(card, role);
  };

  const stopNestedCardActivation = (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (typeof event.stopImmediatePropagation === 'function') {
      event.stopImmediatePropagation();
    }
  };

  const updateSeriesRole = async (card, series, option) => {
    if (!series?.id) return;
    const role = option.role(series);
    const host = card.querySelector('.cvi-role-controls');
    host?.classList.add('is-busy');
    host?.setAttribute('aria-busy', 'true');
    try {
      const response = await window.fetch(`${CVI_API_BASE}/series/${series.id}/role`, {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ role })
      });
      if (!response.ok) {
        const message = await response.text().catch(() => '');
        throw new Error(message || `HTTP ${response.status}`);
      }
      const payload = await response.json().catch(() => ({}));
      series.role = payload.role || role;
      if (series.role !== 'lge_sax') series.is_tissue_lge_primary = false;
      const cached = seriesCache.series.find((item) => item.id === series.id);
      if (cached) {
        cached.role = series.role;
        cached.is_tissue_lge_primary = series.is_tissue_lge_primary;
      }
      if (window.__cviSeriesCache?.series) {
        const publicCached = window.__cviSeriesCache.series.find((item) => Number(item.id) === series.id);
        if (publicCached) {
          publicCached.role = series.role;
          publicCached.is_tissue_lge_primary = series.is_tissue_lge_primary;
        }
      }
      setOverviewCardRoleText(card, series.role);
      document.querySelectorAll('.overview-grid .overview-card').forEach((overviewCard, index) => {
        const overviewSeries = getOverviewCardSeries(overviewCard, index);
        if (overviewSeries) updateSeriesRoleControlsState(overviewCard, overviewSeries);
      });
      window.dispatchEvent(new CustomEvent('cvi:series-role-updated', {
        detail: { seriesId: series.id, role: series.role }
      }));
    } catch (error) {
      window.alert(`序列角色更新失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      host?.classList.remove('is-busy');
      host?.removeAttribute('aria-busy');
    }
  };

  const createOverviewRoleChoice = (card, series, option) => {
    const choice = document.createElement('span');
    choice.className = 'cvi-role-choice';
    choice.dataset.roleKey = option.key;
    choice.setAttribute('role', 'button');
    choice.setAttribute('tabindex', '0');
    choice.textContent = option.label;
    choice.title = option.key === 'lge'
      ? '指定为 LGE；描述含 4CH/LAX 时保存为 lge_lax，否则保存为 lge_sax。'
      : `指定序列角色为 ${option.label}`;
    ['pointerdown', 'mousedown'].forEach((eventName) => {
      choice.addEventListener(eventName, stopNestedCardActivation);
    });
    choice.addEventListener('click', (event) => {
      stopNestedCardActivation(event);
      if (!choice.closest('.cvi-role-controls')?.classList.contains('is-busy')) {
        updateSeriesRole(card, series, option);
      }
    });
    choice.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      stopNestedCardActivation(event);
      if (!choice.closest('.cvi-role-controls')?.classList.contains('is-busy')) {
        updateSeriesRole(card, series, option);
      }
    });
    return choice;
  };

  const setTissueLgePrimary = async (card, series) => {
    const effectivePrimary = getEffectiveTissueLgePrimary();
    if (!series?.id || series.role !== 'lge_sax' || Number(series.id) === effectivePrimary.seriesId) return;
    const host = card.querySelector('.cvi-role-controls');
    host?.classList.add('is-busy');
    host?.setAttribute('aria-busy', 'true');
    try {
      const response = await window.fetch(`${CVI_API_BASE}/series/${series.id}/tissue-lge-primary`, {
        method: 'POST',
        headers: { Accept: 'application/json' }
      });
      if (!response.ok) {
        const message = await response.text().catch(() => '');
        throw new Error(message || `HTTP ${response.status}`);
      }
      seriesCache.series.forEach((item) => {
        item.is_tissue_lge_primary = item.id === series.id;
      });
      if (window.__cviSeriesCache?.series) {
        window.__cviSeriesCache.series.forEach((item) => {
          item.is_tissue_lge_primary = Number(item.id) === series.id;
        });
      }
      window.dispatchEvent(new CustomEvent('cvi:tissue-lge-primary-updated', {
        detail: { studyId: seriesCache.studyId, seriesId: series.id }
      }));
      document.querySelectorAll('.overview-grid .overview-card').forEach((overviewCard, index) => {
        const overviewSeries = getOverviewCardSeries(overviewCard, index);
        if (overviewSeries) updateSeriesRoleControlsState(overviewCard, overviewSeries);
        overviewCard.querySelector('.cvi-role-controls')?.classList.remove('is-busy');
        overviewCard.querySelector('.cvi-role-controls')?.removeAttribute('aria-busy');
      });
    } catch (error) {
      window.alert(`Tissue LGE 序列设置失败：${error instanceof Error ? error.message : String(error)}`);
      host?.classList.remove('is-busy');
      host?.removeAttribute('aria-busy');
    }
  };

  const createTissueLgePrimaryChoice = (card, series) => {
    const choice = document.createElement('span');
    choice.className = 'cvi-role-choice cvi-tissue-lge-choice';
    choice.dataset.roleKey = 'tissue-lge-primary';
    choice.setAttribute('role', 'button');
    choice.setAttribute('tabindex', '0');
    ['pointerdown', 'mousedown'].forEach((eventName) => {
      choice.addEventListener(eventName, stopNestedCardActivation);
    });
    const activate = (event) => {
      stopNestedCardActivation(event);
      if (!choice.closest('.cvi-role-controls')?.classList.contains('is-busy')) {
        setTissueLgePrimary(card, series);
      }
    };
    choice.addEventListener('click', activate);
    choice.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') activate(event);
    });
    return choice;
  };

  const ensureOverviewSeriesRoleControls = () => {
    const cards = Array.from(document.querySelectorAll('.overview-grid .overview-card'));
    if (!cards.length) return;
    refreshCurrentStudySeriesCache();
    const availableSeries = seriesCache.series.length
      ? seriesCache.series
      : Array.isArray(window.__cviSeriesCache?.series)
        ? window.__cviSeriesCache.series
        : [];

    cards.forEach((card, index) => {
      if (!(card instanceof HTMLElement)) return;
      const seriesId = getSeriesIdFromOverviewCard(card);
      const series = (seriesId
        ? availableSeries.find((item) => Number(item.id) === seriesId)
        : null) || getOverviewCardSeries(card, index);
      if (!series?.id) return;
      card.dataset.cviSeriesId = String(series.id);

      let host = card.querySelector('.cvi-role-controls');
      if (!host) {
        host = document.createElement('span');
        host.className = 'cvi-role-controls';
        host.setAttribute('aria-label', '手动指定序列角色');
        overviewRoleOptions.forEach((option) => {
          host.appendChild(createOverviewRoleChoice(card, series, option));
        });
        host.appendChild(createTissueLgePrimaryChoice(card, series));
        const body = card.querySelector('div') || card;
        body.appendChild(host);
      }

      updateSeriesRoleControlsState(card, series);
    });
  };

  const findButtonByText = (root, pattern) => {
    return Array.from(root.querySelectorAll('button')).find((button) => {
      return pattern.test((button.textContent || '').trim());
    }) || null;
  };

  const getMainViewerCard = () => {
    const grid = document.querySelector('.viewer-grid');
    if (!grid) return null;
    return Array.from(grid.children).find((child) => {
      return child.classList?.contains('viewer-card')
        && !child.classList.contains('cvi-zoom-placeholder')
        && !child.closest('.cvi-reference-stack');
    }) || null;
  };

  const isZoomableViewerCard = (card) => {
    if (!card) return false;
    if (!card.querySelector('.viewer-overlay')) return false;
    const heading = card.querySelector('.viewer-head h3')?.textContent || '';
    return !/Reference/i.test(heading);
  };

  const getZoomCardTitle = (card) => {
    const heading = card?.querySelector('.viewer-head h3')?.textContent?.trim() || '当前视图';
    return /放大标注$/.test(heading) ? heading : `${heading} 放大标注`;
  };

  let active4chZoom = null;

  const dispatchViewerResize = () => {
    window.dispatchEvent(new Event('resize'));
    window.setTimeout(() => window.dispatchEvent(new Event('resize')), 80);
  };

  const close4chZoomModal = () => {
    if (!active4chZoom) return;
    const { modal, card, keydown } = active4chZoom;
    window.removeEventListener('keydown', keydown);
    modal?.remove();
    card?.classList.remove('cvi-4ch-zoom-card');
    if (card) delete card.dataset.cviZoomActive;
    document.body.classList.remove('cvi-zoom-open', 'cvi-zoom-with-tools');
    active4chZoom = null;
    dispatchViewerResize();
  };

  const open4chZoomModal = (card) => {
    if (!card || active4chZoom?.card === card) return;
    close4chZoomModal();

    const modal = document.createElement('div');
    modal.className = 'cvi-zoom-modal';
    modal.innerHTML = [
      '<div class="cvi-zoom-header">',
      `<strong>${getZoomCardTitle(card)}</strong>`,
      '<span>Esc 关闭</span>',
      '<button type="button" class="ghost-button cvi-zoom-close">关闭</button>',
      '</div>'
    ].join('');

    const closeButton = modal.querySelector('.cvi-zoom-close');
    closeButton?.addEventListener('click', close4chZoomModal);
    modal.addEventListener('mousedown', (event) => {
      if (event.target === modal) close4chZoomModal();
    });

    const keydown = (event) => {
      if (event.key === 'Escape') close4chZoomModal();
    };

    document.body.appendChild(modal);
    document.body.classList.add('cvi-zoom-open');
    if (document.querySelector('.inspector')) {
      document.body.classList.add('cvi-zoom-with-tools');
    }
    card.classList.add('cvi-4ch-zoom-card');
    card.dataset.cviZoomActive = '1';
    active4chZoom = { modal, card, keydown };
    window.addEventListener('keydown', keydown);
    dispatchViewerResize();
  };

  const ensure4chZoomButton = () => {
    if (active4chZoom && (!active4chZoom.card?.isConnected || !isZoomableViewerCard(active4chZoom.card))) {
      close4chZoomModal();
    }

    const card = getMainViewerCard();
    document.querySelectorAll('.cvi-enlarge-4ch-button').forEach((button) => {
      if (!card?.contains(button)) button.remove();
    });
    if (!card) return;

    const tools = card.querySelector('.viewer-head-tools');
    if (!tools) return;

    let button = tools.querySelector('.cvi-enlarge-4ch-button');
    if (!isZoomableViewerCard(card)) {
      button?.remove();
      return;
    }

    if (!button) {
      button = document.createElement('button');
      button.type = 'button';
      button.className = 'ghost-button cvi-enlarge-4ch-button';
      button.addEventListener('click', () => {
        if (card.classList.contains('cvi-4ch-zoom-card')) {
          close4chZoomModal();
        } else {
          open4chZoomModal(card);
        }
      });
      tools.insertBefore(button, tools.firstChild);
    }

    const isOpen = card.classList.contains('cvi-4ch-zoom-card');
    const nextText = isOpen ? '退出放大' : '放大标注';
    const nextTitle = isOpen ? `关闭${getZoomCardTitle(card)}` : `打开更大的${getZoomCardTitle(card)}`;
    if ((button.textContent || '') !== nextText) button.textContent = nextText;
    if (button.title !== nextTitle) button.title = nextTitle;
  };

  const rulerState = {
    active: false,
    drawing: false,
    pointerId: null,
    dragTarget: 'end',
    card: null,
    svg: null,
    frameKey: '',
    series: null,
    start: null,
    end: null
  };

  const currentRulerFrameKey = (series) => {
    const sliceIndex = Number(getNavigatorInput('Slice')?.value || 0);
    const phaseIndex = Number(getNavigatorInput('Phase')?.value || 0);
    return `${Number(series?.id) || 0}:${sliceIndex}:${phaseIndex}`;
  };

  const currentRulerSpacing = (series) => {
    const sliceIndex = Number(getNavigatorInput('Slice')?.value || 0);
    const phaseIndex = Number(getNavigatorInput('Phase')?.value || 0);
    const frame = Array.isArray(series?.frames) ? series.frames.find((item) => (
      Number(item?.slice_index) === sliceIndex && Number(item?.phase_index) === phaseIndex
    )) : null;
    const raw = Array.isArray(frame?.pixel_spacing) && frame.pixel_spacing.length >= 2
      ? frame.pixel_spacing
      : series?.pixel_spacing;
    const spacingX = Number(raw?.[0]);
    const spacingY = Number(raw?.[1]);
    if (!(spacingX > 0) || !(spacingY > 0)) return null;
    return { spacingX, spacingY };
  };

  const rulerPointFromEvent = (svg, event) => {
    const matrix = svg.getScreenCTM?.();
    if (matrix && typeof DOMPoint === 'function') {
      const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
      return { x: point.x, y: point.y };
    }
    const rect = svg.getBoundingClientRect();
    const viewBox = svg.viewBox?.baseVal;
    const width = viewBox?.width || Number(svg.getAttribute('width')) || rect.width;
    const height = viewBox?.height || Number(svg.getAttribute('height')) || rect.height;
    return {
      x: ((event.clientX - rect.left) / Math.max(rect.width, 1)) * width,
      y: ((event.clientY - rect.top) / Math.max(rect.height, 1)) * height
    };
  };

  const rulerLengthMm = () => {
    const spacing = currentRulerSpacing(rulerState.series);
    if (!spacing || !rulerState.start || !rulerState.end) return null;
    const dx = (rulerState.end.x - rulerState.start.x) * spacing.spacingX;
    const dy = (rulerState.end.y - rulerState.start.y) * spacing.spacingY;
    return Math.sqrt(dx * dx + dy * dy);
  };

  const createRulerSvgNode = (name, attributes = {}) => {
    const node = document.createElementNS('http://www.w3.org/2000/svg', name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  };

  const renderRuler = () => {
    document.querySelectorAll('.cvi-ruler-layer').forEach((node) => node.remove());
    const { svg, start, end } = rulerState;
    if (!svg?.isConnected || !start || !end) return;

    const lengthMm = rulerLengthMm();
    const layer = createRulerSvgNode('g', {
      class: 'cvi-ruler-layer',
      'aria-label': lengthMm == null ? '测距：缺少像素间距' : `测距：${lengthMm.toFixed(1)} 毫米`,
      'pointer-events': 'none'
    });
    const line = createRulerSvgNode('line', {
      class: 'cvi-ruler-line',
      x1: start.x,
      y1: start.y,
      x2: end.x,
      y2: end.y,
      'vector-effect': 'non-scaling-stroke'
    });
    const startHandle = createRulerSvgNode('circle', {
      class: 'cvi-ruler-handle', cx: start.x, cy: start.y, r: 3.2,
      'vector-effect': 'non-scaling-stroke'
    });
    const endHandle = createRulerSvgNode('circle', {
      class: 'cvi-ruler-handle', cx: end.x, cy: end.y, r: 3.2,
      'vector-effect': 'non-scaling-stroke'
    });
    const middleX = (start.x + end.x) / 2;
    const middleY = (start.y + end.y) / 2;
    const label = createRulerSvgNode('text', {
      class: 'cvi-ruler-label',
      x: middleX,
      y: middleY - 7,
      'text-anchor': 'middle',
      'paint-order': 'stroke'
    });
    label.textContent = lengthMm == null ? '缺少 PixelSpacing' : `${lengthMm.toFixed(1)} mm`;
    layer.append(line, startHandle, endHandle, label);
    svg.appendChild(layer);
  };

  const clearRuler = () => {
    rulerState.drawing = false;
    rulerState.pointerId = null;
    rulerState.start = null;
    rulerState.end = null;
    document.querySelectorAll('.cvi-ruler-layer').forEach((node) => node.remove());
    document.querySelectorAll('.cvi-ruler-clear-button').forEach((button) => {
      button.hidden = true;
    });
  };

  const setRulerActive = (active) => {
    rulerState.active = Boolean(active);
    rulerState.drawing = false;
    rulerState.pointerId = null;
    document.documentElement.classList.toggle('cvi-ruler-active', rulerState.active);
    document.querySelectorAll('.cvi-ruler-button').forEach((button) => {
      button.classList.toggle('is-active', rulerState.active);
      button.setAttribute('aria-pressed', rulerState.active ? 'true' : 'false');
    });
  };

  const nearestRulerHandle = (event) => {
    if (!rulerState.svg || !rulerState.start || !rulerState.end) return null;
    const startClient = imagePointToClient(rulerState.svg, rulerState.start);
    const endClient = imagePointToClient(rulerState.svg, rulerState.end);
    const distance = (point) => Math.hypot(event.clientX - point.clientX, event.clientY - point.clientY);
    if (distance(startClient) <= 14) return 'start';
    if (distance(endClient) <= 14) return 'end';
    return null;
  };

  const stopRulerEvent = (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (typeof event.stopImmediatePropagation === 'function') event.stopImmediatePropagation();
  };

  const handleRulerPointerDown = (event) => {
    if (!rulerState.active || event.button !== 0) return;
    const svg = event.target instanceof Element ? event.target.closest('.viewer-overlay') : null;
    const card = svg?.closest('.viewer-card');
    if (!svg || card !== getMainViewerCard() || mainCineRole() !== 'cine_lax_4ch') return;
    stopRulerEvent(event);

    rulerState.card = card;
    rulerState.svg = svg;
    rulerState.series = mainCineSeries();
    rulerState.frameKey = currentRulerFrameKey(rulerState.series);
    rulerState.pointerId = event.pointerId;
    rulerState.drawing = true;
    const handle = nearestRulerHandle(event);
    rulerState.dragTarget = handle || 'end';
    const point = rulerPointFromEvent(svg, event);
    if (handle === 'start') {
      rulerState.start = point;
    } else if (handle === 'end') {
      rulerState.end = point;
    } else {
      rulerState.start = point;
      rulerState.end = point;
    }
    renderRuler();
  };

  const handleRulerPointerMove = (event) => {
    if (!rulerState.active || !rulerState.drawing || event.pointerId !== rulerState.pointerId) return;
    stopRulerEvent(event);
    const point = rulerPointFromEvent(rulerState.svg, event);
    rulerState[rulerState.dragTarget] = point;
    renderRuler();
  };

  const handleRulerPointerUp = (event) => {
    if (!rulerState.active || !rulerState.drawing || event.pointerId !== rulerState.pointerId) return;
    stopRulerEvent(event);
    rulerState[rulerState.dragTarget] = rulerPointFromEvent(rulerState.svg, event);
    rulerState.drawing = false;
    rulerState.pointerId = null;
    if (rulerState.start && rulerState.end && Math.hypot(
      rulerState.end.x - rulerState.start.x,
      rulerState.end.y - rulerState.start.y
    ) < 1) {
      clearRuler();
      return;
    }
    renderRuler();
    document.querySelectorAll('.cvi-ruler-clear-button').forEach((button) => {
      button.hidden = false;
    });
  };

  const ensureLaxSeriesSelector = () => {
    const card = getMainViewerCard();
    const tools = card?.querySelector('.viewer-head-tools');
    const roleOptions = [
      { role: 'cine_lax_4ch', label: '4CH' },
      { role: 'cine_lax_2ch', label: '2CH' },
      { role: 'cine_lax_3ch', label: '3CH' }
    ];
    const available = roleOptions.filter((option) => (
      (window.__cviSeriesCache?.series || []).some((series) => series?.role === option.role)
    ));
    const shouldShow = activeProtocolKey() === 'function4ch';
    document.querySelectorAll('.cvi-lax-series-selector').forEach((node) => {
      if (!card?.contains(node) || available.length < 2 || !shouldShow) node.remove();
    });
    if (!card || !tools || available.length < 2 || !shouldShow) return;

    const preferred = String(window.__cviPreferredLaxRole || storage.getItem('cvi.embedded.laxRole') || 'cine_lax_4ch');
    const selected = available.find((option) => option.role === preferred) || available[0];
    window.__cviPreferredLaxRole = selected.role;
    const title = card.querySelector('.viewer-head h3');
    if (title && title.textContent !== `Cine ${selected.label} Workspace`) {
      title.textContent = `Cine ${selected.label} Workspace`;
    }

    let select = tools.querySelector('.cvi-lax-series-selector');
    if (!(select instanceof HTMLSelectElement)) {
      select = document.createElement('select');
      select.className = 'cvi-lax-series-selector';
      select.title = '切换长轴 cine 序列';
      select.addEventListener('change', async () => {
        const nextRole = select.value;
        if (!roleOptions.some((option) => option.role === nextRole)) return;
        if (typeof window.__cviFlushContourAutoSaveByKey === 'function') {
          const activeKey = window.__cviGetContourAutoSaveKey?.() || '';
          if (activeKey) await window.__cviFlushContourAutoSaveByKey(activeKey);
        }
        storage.setItem('cvi.embedded.laxRole', nextRole);
        window.__cviPreferredLaxRole = nextRole;
        window.location.reload();
      });
      tools.insertBefore(select, tools.firstChild);
    }
    const optionsHash = available.map((option) => option.role).join('|');
    if (select.dataset.optionsHash !== optionsHash) {
      select.dataset.optionsHash = optionsHash;
      select.replaceChildren(...available.map((option) => {
        const element = document.createElement('option');
        element.value = option.role;
        element.textContent = option.label;
        return element;
      }));
    }
    select.value = selected.role;
  };

  const ensure4chRuler = () => {
    const card = getMainViewerCard();
    const is4ch = mainCineRole().startsWith('cine_lax_');
    document.querySelectorAll('.cvi-ruler-button, .cvi-ruler-clear-button').forEach((button) => {
      if (!is4ch || !card?.contains(button)) button.remove();
    });
    if (!card || !is4ch) {
      setRulerActive(false);
      clearRuler();
      return;
    }

    const svg = card.querySelector('.viewer-overlay');
    const tools = card.querySelector('.viewer-head-tools');
    const series = mainCineSeries();
    if (!svg || !tools || !series) return;

    let button = tools.querySelector('.cvi-ruler-button');
    if (!button) {
      button = document.createElement('button');
      button.type = 'button';
      button.className = 'ghost-button cvi-ruler-button';
      button.textContent = '测距';
      button.title = '在长轴图像上拖动测量直线长度';
      button.setAttribute('aria-pressed', 'false');
      button.addEventListener('click', () => setRulerActive(!rulerState.active));
      tools.insertBefore(button, tools.firstChild);
    }

    let clearButton = tools.querySelector('.cvi-ruler-clear-button');
    if (!clearButton) {
      clearButton = document.createElement('button');
      clearButton.type = 'button';
      clearButton.className = 'ghost-button cvi-ruler-clear-button';
      clearButton.textContent = '清除测距';
      clearButton.title = '清除当前帧临时测量';
      clearButton.hidden = !rulerState.start;
      clearButton.addEventListener('click', clearRuler);
      button.insertAdjacentElement('afterend', clearButton);
    }

    const nextFrameKey = currentRulerFrameKey(series);
    if (rulerState.frameKey && rulerState.frameKey !== nextFrameKey) clearRuler();
    if (rulerState.svg && rulerState.svg !== svg) clearRuler();
    rulerState.card = card;
    rulerState.svg = svg;
    rulerState.series = series;
    rulerState.frameKey = nextFrameKey;
    button.classList.toggle('is-active', rulerState.active);
    button.setAttribute('aria-pressed', rulerState.active ? 'true' : 'false');
    clearButton.hidden = !rulerState.start;
  };

  const getSelectedContourContext = () => {
    const card = getMainViewerCard();
    const svg = card?.querySelector('.viewer-overlay');
    const path = svg?.querySelector('path.contour.is-selected');
    if (!card || !svg || !path) return null;

    const contourKey = Array.from(path.classList).find((className) => {
      return className.startsWith('contour-') && className !== 'contour';
    })?.replace(/^contour-/, '');
    if (!contourKey) return null;

    return { card, svg, path, contourKey };
  };

  const contourLabelCandidates = {
    la: ['左房'],
    ra: ['右房'],
    endo: ['左室内膜', '左室'],
    epi: ['左室外膜'],
    rv: ['右室腔', '右室'],
    fat: ['心外膜脂肪'],
    fat_outer: ['脂肪壁层', '脂肪外层线'],
    remote: ['正常心肌'],
    enhanced: ['强化区'],
    exclude: ['排除区'],
    mvo: ['MVO']
  };

  const getContourKeyFromNode = (node) => {
    if (!(node instanceof Element)) return null;
    return Array.from(node.classList).find((className) => {
      return className.startsWith('contour-') && className !== 'contour';
    })?.replace(/^contour-/, '') || null;
  };

  const getContourPanel = () => {
    return Array.from(document.querySelectorAll('.tool-group')).find((group) => {
      const title = group.querySelector('strong')?.textContent?.trim() || '';
      return title === '勾画部位' || title === '轮廓工具';
    }) || null;
  };

  const isContourModeActive = () => {
    const drawButton = findButtonByText(document, /^勾画$/);
    return Boolean(drawButton?.classList.contains('is-active'));
  };

  const ensureContourModeActive = () => {
    const drawButton = findButtonByText(document, /^勾画$/);
    if (drawButton && !drawButton.classList.contains('is-active')) {
      drawButton.click();
    }
  };

  const findContourKeyButton = (key) => {
    const labels = contourLabelCandidates[key] || [key];
    const panel = getContourPanel() || document;
    const buttons = Array.from(panel.querySelectorAll('.tool-pills button'));
    return buttons.find((button) => {
      const text = (button.textContent || '').trim();
      return labels.includes(text);
    }) || null;
  };

  const selectContourKey = (key) => {
    ensureContourModeActive();
    const button = findContourKeyButton(key);
    if (button && !button.classList.contains('is-active')) {
      button.click();
    }
    return button;
  };

  const ensureExcludeRegionControls = () => {
    const panel = getContourPanel();
    if (!(panel instanceof HTMLElement)) return;
    const excludeButton = findContourKeyButton('exclude');
    const isExcludeActive = Boolean(excludeButton?.classList.contains('is-active'));
    let controls = panel.querySelector('.cvi-exclude-region-controls');
    if (!isExcludeActive) {
      controls?.remove();
      return;
    }
    if (!controls) {
      controls = document.createElement('div');
      controls.className = 'cvi-exclude-region-controls';
      controls.innerHTML = [
        '<button type="button" data-cvi-exclude-action="finish">退出排除绘制</button>',
        '<button type="button" data-cvi-exclude-action="undo">撤销上一个</button>',
        '<button type="button" data-cvi-exclude-action="clear">清空本帧排除区</button>'
      ].join('');
      controls.addEventListener('click', (event) => {
        const button = event.target instanceof Element ? event.target.closest('button[data-cvi-exclude-action]') : null;
        if (!(button instanceof HTMLButtonElement)) return;
        event.preventDefault();
        event.stopPropagation();
        const action = button.getAttribute('data-cvi-exclude-action');
        if (action === 'finish') {
          findButtonByText(document, /^浏览$/)?.click();
          return;
        }
        selectContourKey('exclude');
        if (action === 'undo') {
          findButtonByText(document, /^撤销$/)?.click();
          return;
        }
        if (action === 'clear') {
          findButtonByText(document, /^清空当前轮廓$/)?.click();
        }
      });
    }
    const toolCard = panel.querySelector('.contour-tool-card');
    if (toolCard instanceof HTMLElement) {
      toolCard.insertAdjacentElement('afterend', controls);
    } else if (controls.parentElement !== panel) {
      panel.appendChild(controls);
    }
  };

  const isExcludeContourActive = () => {
    const excludeButton = findContourKeyButton('exclude');
    return Boolean(excludeButton?.classList.contains('is-active'));
  };

  const ensureExcludePointToolGuard = () => {
    const pointButtons = Array.from(document.querySelectorAll('button')).filter((button) => {
      return /^点状勾画$/.test((button.textContent || '').trim());
    });
    if (!pointButtons.length) return;

    if (!isExcludeContourActive()) {
      pointButtons.forEach((button) => {
        if (button.dataset.cviExcludePointHidden !== '1') return;
        button.hidden = false;
        button.style.display = '';
        button.disabled = button.dataset.cviExcludePointWasDisabled === '1';
        button.title = button.dataset.cviExcludePointTitle || '';
        delete button.dataset.cviExcludePointHidden;
        delete button.dataset.cviExcludePointWasDisabled;
        delete button.dataset.cviExcludePointTitle;
      });
      return;
    }

    const activePointButton = pointButtons.find((button) => button.classList.contains('is-active'));
    if (activePointButton) {
      const fallbackButton = findButtonByText(document, /^一笔画线$/) || findButtonByText(document, /^毛刷$/);
      if (fallbackButton && !fallbackButton.disabled) fallbackButton.click();
    }

    pointButtons.forEach((button) => {
      if (button.dataset.cviExcludePointHidden !== '1') {
        button.dataset.cviExcludePointWasDisabled = button.disabled ? '1' : '0';
        button.dataset.cviExcludePointTitle = button.title || '';
      }
      button.dataset.cviExcludePointHidden = '1';
      button.disabled = true;
      button.hidden = true;
      button.style.display = 'none';
      button.title = '排除区请用一笔画线、毛刷或 SAM 生成独立扣除区域。';
    });
  };

  const wait = (ms = 60) => new Promise((resolve) => window.setTimeout(resolve, ms));

  let activeContourMenu = null;
  let lastAutoOpenSignature = '';
  let lastDrawPreviewSignature = '';
  let drawAutoOpenRunId = 0;

  const closeContourMenu = () => {
    const menu = activeContourMenu?.menu;
    if (menu?.isConnected) menu.remove();
    activeContourMenu = null;
  };

  const updateContourMenu = async () => {
    if (!activeContourMenu?.menu?.isConnected) return;
    const { contourKey, menu } = activeContourMenu;
    const title = menu.querySelector('[data-role="title"]');
    const toggleButton = menu.querySelector('[data-role="toggle"]');
    const selectButton = menu.querySelector('[data-role="select"]');
    const matchedButton = selectContourKey(contourKey);
    await wait(40);
    const liveToggle = findButtonByText(document, /^改为开口$|^闭合轮廓$/);

    if (title) {
      title.textContent = (matchedButton?.textContent || contourLabelCandidates[contourKey]?.[0] || contourKey).trim();
    }
    if (selectButton) {
      selectButton.textContent = matchedButton?.classList.contains('is-active') ? '已选中当前轮廓' : '选中当前轮廓';
    }
    if (toggleButton) {
      toggleButton.textContent = liveToggle ? (liveToggle.textContent || '').trim() : '切换开口 / 闭合';
    }
  };

  const runContourAction = async (contourKey, pattern) => {
    selectContourKey(contourKey);
    await wait(70);
    const actionButton = findButtonByText(document, pattern);
    if (!actionButton || actionButton.disabled) return false;
    actionButton.click();
    return true;
  };

  const createContourMenuButton = (label, role, onClick, tone = 'default') => {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.role = role;
    button.textContent = label;
    button.style.border = '1px solid rgba(255,255,255,.12)';
    button.style.borderRadius = '10px';
    button.style.padding = '8px 10px';
    button.style.background = tone === 'danger' ? 'rgba(255,107,107,.16)' : 'rgba(255,255,255,.08)';
    button.style.color = tone === 'danger' ? '#ffd6d6' : '#f4f4f4';
    button.style.cursor = 'pointer';
    button.style.textAlign = 'left';
    button.style.fontSize = '12px';
    button.style.lineHeight = '1.25';
    button.addEventListener('click', onClick);
    return button;
  };

  const openContourMenu = async ({ contourKey, clientX, clientY }) => {
    closeContourMenu();
    selectContourKey(contourKey);

    const menu = document.createElement('div');
    menu.className = 'cvi-contour-context-menu';
    menu.style.position = 'fixed';
    menu.style.left = `${Math.min(clientX + 12, window.innerWidth - 236)}px`;
    menu.style.top = `${Math.min(clientY + 12, window.innerHeight - 196)}px`;
    menu.style.zIndex = '9999';
    menu.style.width = '220px';
    menu.style.display = 'flex';
    menu.style.flexDirection = 'column';
    menu.style.gap = '8px';
    menu.style.padding = '12px';
    menu.style.borderRadius = '14px';
    menu.style.background = 'rgba(14,16,20,.96)';
    menu.style.border = '1px solid rgba(255,255,255,.12)';
    menu.style.boxShadow = '0 18px 40px rgba(0,0,0,.42)';
    menu.style.backdropFilter = 'blur(14px)';
    menu.style.webkitBackdropFilter = 'blur(14px)';

    const kicker = document.createElement('div');
    kicker.textContent = '轮廓菜单';
    kicker.style.fontSize = '11px';
    kicker.style.letterSpacing = '.08em';
    kicker.style.textTransform = 'uppercase';
    kicker.style.color = '#aeb5bc';

    const title = document.createElement('strong');
    title.dataset.role = 'title';
    title.textContent = contourLabelCandidates[contourKey]?.[0] || contourKey;
    title.style.fontSize = '14px';
    title.style.color = '#f7f7f7';

    const copy = document.createElement('div');
    copy.textContent = '右键到哪条线，就直接操作哪条线。';
    copy.style.fontSize = '12px';
    copy.style.lineHeight = '1.4';
    copy.style.color = '#b9c0c7';

    const actions = document.createElement('div');
    actions.style.display = 'flex';
    actions.style.flexDirection = 'column';
    actions.style.gap = '8px';

    actions.appendChild(createContourMenuButton('选中当前轮廓', 'select', async () => {
      selectContourKey(contourKey);
      await wait(50);
      updateContourMenu();
    }));
    actions.appendChild(createContourMenuButton('切换开口 / 闭合', 'toggle', async () => {
      await runContourAction(contourKey, /^改为开口$|^闭合轮廓$/);
      await wait(50);
      updateContourMenu();
    }));
    actions.appendChild(createContourMenuButton('清空当前轮廓', 'clear', async () => {
      const ok = await runContourAction(contourKey, /^清空当前轮廓$/);
      if (ok) closeContourMenu();
    }, 'danger'));

    menu.append(kicker, title, copy, actions);
    document.body.appendChild(menu);
    activeContourMenu = { menu, contourKey };
    await updateContourMenu();
  };

  const parseContourVertices = (path) => {
    const d = path?.getAttribute('d') || '';
    const matches = Array.from(d.matchAll(/([MLC])([^MLC]*)/g));
    const points = [];

    matches.forEach(([, command, payload]) => {
      const values = (payload.match(/-?\d*\.?\d+/g) || []).map(Number);
      if (command === 'M' || command === 'L') {
        for (let index = 0; index + 1 < values.length; index += 2) {
          points.push({ x: values[index], y: values[index + 1] });
        }
      } else if (command === 'C') {
        for (let index = 0; index + 5 < values.length; index += 6) {
          points.push({ x: values[index + 4], y: values[index + 5] });
        }
      }
    });

    return points.filter((point, index) => {
      if (index === 0) return true;
      const previous = points[index - 1];
      return Math.hypot(point.x - previous.x, point.y - previous.y) > 0.01;
    });
  };

  const clearDrawContourPreviews = () => {
    document.querySelectorAll('.cvi-draw-point-preview').forEach((node) => node.remove());
    lastDrawPreviewSignature = '';
  };

  const getDrawPreviewSignature = (context) => {
    const activeCell = document.querySelector('[data-cvi-frame-cell].is-active');
    const sliceIndex = activeCell?.getAttribute('data-cvi-slice-index') || '';
    const phaseIndex = activeCell?.getAttribute('data-cvi-phase-index') || '';
    const image = context.card.querySelector('img')?.getAttribute('src') || '';
    const pathData = context.path.getAttribute('d') || '';
    return `${context.contourKey}|${sliceIndex}:${phaseIndex}|${image}|${pathData}`;
  };

  const ensureDrawContourPreview = () => {
    const context = getSelectedContourContext();
    const drawButton = findButtonByText(document, /^点状勾画$/);
    const svg = context?.svg;

    if (!svg || !drawButton?.classList.contains('is-active')) {
      lastAutoOpenSignature = '';
      clearDrawContourPreviews();
      return;
    }

    const signature = getDrawPreviewSignature(context);
    if (lastDrawPreviewSignature && lastDrawPreviewSignature !== signature) {
      clearDrawContourPreviews();
    }
    lastDrawPreviewSignature = signature;

    const points = parseContourVertices(context.path);
    if (!points.length) {
      clearDrawContourPreviews();
      return;
    }

    const existing = svg.querySelector('.cvi-draw-point-preview');
    const layer = existing || document.createElementNS('http://www.w3.org/2000/svg', 'g');
    layer.setAttribute('class', 'cvi-draw-point-preview');
    layer.setAttribute('pointer-events', 'none');
    layer.replaceChildren(...points.map((point, index) => {
      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', String(point.x));
      circle.setAttribute('cy', String(point.y));
      circle.setAttribute('r', index === points.length - 1 ? '1.45' : '1.15');
      circle.setAttribute('fill', index === points.length - 1 ? '#f5ff8f' : '#d8f271');
      circle.setAttribute('stroke', '#050607');
      circle.setAttribute('stroke-width', '0.42');
      circle.setAttribute('opacity', index === points.length - 1 ? '1' : '0.92');
      return circle;
    }));

    if (!existing) svg.appendChild(layer);
  };

  const ensureDrawContourStaysOpen = () => {
    lastAutoOpenSignature = '';
  };

  const queueDrawContourAutoOpen = () => {
    drawAutoOpenRunId += 1;
  };

  const syncContourHitTargets = (svg) => {
    const drawButton = findButtonByText(document, /^点状勾画$/);
    const drawModeActive = Boolean(drawButton?.classList.contains('is-active'));
    svg.querySelectorAll('.cvi-contour-hit-target').forEach((node) => node.remove());

    svg.querySelectorAll('path.contour').forEach((path) => {
      if (!(path instanceof SVGPathElement)) return;
      path.style.pointerEvents = drawModeActive ? 'none' : '';
    });

    if (drawModeActive) {
      return;
    }

    svg.querySelectorAll('path.contour').forEach((path) => {
      if (!(path instanceof SVGPathElement)) return;
      const contourKey = getContourKeyFromNode(path);
      if (!contourKey) return;

      const hit = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      hit.setAttribute('class', `cvi-contour-hit-target contour-${contourKey}`);
      hit.setAttribute('d', path.getAttribute('d') || '');
      hit.setAttribute('fill', 'none');
      hit.setAttribute('stroke', 'transparent');
      hit.setAttribute('stroke-width', path.classList.contains('is-selected') ? '16' : '14');
      hit.setAttribute('vector-effect', 'non-scaling-stroke');
      hit.setAttribute('pointer-events', 'stroke');

      hit.addEventListener('pointerdown', (event) => {
        if (event.button === 2) return;
        selectContourKey(contourKey);
      });

      hit.addEventListener('contextmenu', (event) => {
        event.preventDefault();
        event.stopPropagation();
        openContourMenu({
          contourKey,
          clientX: event.clientX,
          clientY: event.clientY
        });
      });

      path.parentNode?.insertBefore(hit, path);
    });
  };

  const ensureContourContextTools = () => {
    const card = getMainViewerCard();
    const svg = card?.querySelector('.viewer-overlay');

    if (!svg) {
      closeContourMenu();
      return;
    }

    if (svg.dataset.cviContourContextBound !== '1') {
      svg.dataset.cviContourContextBound = '1';

      svg.addEventListener('pointerdown', (event) => {
        const drawButton = findButtonByText(document, /^点状勾画$/);
        if (drawButton?.classList.contains('is-active')) return;
        const path = event.target instanceof Element ? event.target.closest('path.contour') : null;
        if (!path || event.button === 2) return;
        const contourKey = getContourKeyFromNode(path);
        if (contourKey) {
          selectContourKey(contourKey);
        }
      }, true);

      svg.addEventListener('pointerup', (event) => {
        if (event.button !== 0) return;
        queueDrawContourAutoOpen();
      }, true);

      svg.addEventListener('contextmenu', (event) => {
        const path = event.target instanceof Element ? event.target.closest('path.contour') : null;
        if (!path) return;
        const contourKey = getContourKeyFromNode(path);
        if (!contourKey) return;

        event.preventDefault();
        event.stopPropagation();
        if (typeof event.stopImmediatePropagation === 'function') {
          event.stopImmediatePropagation();
        }
        openContourMenu({
          contourKey,
          clientX: event.clientX,
          clientY: event.clientY
        });
      }, true);
    }

    updateContourMenu();
  };

  const syncContourHandleHitTargets = () => {
    const card = getMainViewerCard();
    const svg = card?.querySelector('.viewer-overlay');

    document.querySelectorAll('.cvi-contour-handle-hit').forEach((node) => node.remove());
    if (!svg) return;

    const activeModeLabel = Array.from(document.querySelectorAll('button.is-active')).map((button) => {
      return (button.textContent || '').trim();
    }).find((label) => /^(点状微调|微调模式)$/.test(label)) || '';

    const hitRadius = activeModeLabel === '点状微调' ? 6 : activeModeLabel === '微调模式' ? 5 : 0;
    if (!hitRadius) return;

    svg.querySelectorAll('circle.contour-handle').forEach((handle) => {
      if (!(handle instanceof SVGCircleElement)) return;

      const hit = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      hit.setAttribute('class', 'cvi-contour-handle-hit');
      hit.setAttribute('cx', handle.getAttribute('cx') || '0');
      hit.setAttribute('cy', handle.getAttribute('cy') || '0');
      hit.setAttribute('r', String(hitRadius));
      hit.setAttribute('fill', 'transparent');
      hit.setAttribute('stroke', 'transparent');
      hit.setAttribute('stroke-width', '0');
      hit.setAttribute('pointer-events', 'all');

      hit.addEventListener('pointerdown', (event) => {
        event.preventDefault();
        event.stopPropagation();
        handle.dispatchEvent(new PointerEvent('pointerdown', {
          bubbles: true,
          cancelable: true,
          composed: true,
          pointerId: event.pointerId,
          pointerType: event.pointerType || 'mouse',
          isPrimary: event.isPrimary,
          button: event.button,
          buttons: event.buttons,
          altKey: event.altKey,
          ctrlKey: event.ctrlKey,
          metaKey: event.metaKey,
          shiftKey: event.shiftKey,
          clientX: event.clientX,
          clientY: event.clientY
        }));
      });

      hit.addEventListener('contextmenu', (event) => {
        event.preventDefault();
        event.stopPropagation();
      });

      handle.parentNode?.insertBefore(hit, handle);
    });
  };

  const imagePointToClient = (svg, point) => {
    const rect = svg.getBoundingClientRect();
    const viewBox = svg.viewBox?.baseVal;
    const width = viewBox?.width || Number(svg.getAttribute('width')) || rect.width;
    const height = viewBox?.height || Number(svg.getAttribute('height')) || rect.height;
    return {
      clientX: rect.left + (point.x / Math.max(width, 1)) * rect.width,
      clientY: rect.top + (point.y / Math.max(height, 1)) * rect.height
    };
  };

  const dispatchPointer = (target, type, point, buttons) => {
    const event = new PointerEvent(type, {
      bubbles: true,
      cancelable: true,
      pointerId: 4821,
      pointerType: 'mouse',
      isPrimary: true,
      button: 0,
      buttons,
      clientX: point.clientX,
      clientY: point.clientY
    });
    target.dispatchEvent(event);
  };

  const runAutoFitCurrentContour = async (button) => {
    const context = getSelectedContourContext();
    if (!context) {
      window.alert('请先选中一个已经勾好的轮廓，再执行自动贴合。');
      return;
    }

    const { card, svg, path } = context;
    let box;
    try {
      box = path.getBBox();
    } catch {
      window.alert('当前轮廓暂时无法读取，请先切换到勾画模式后再试。');
      return;
    }

    const viewBox = svg.viewBox?.baseVal;
    const width = viewBox?.width || 0;
    const height = viewBox?.height || 0;
    if (!width || !height || box.width < 4 || box.height < 4) {
      window.alert('当前轮廓太小，无法用于自动贴合。');
      return;
    }

    const margin = Math.max(4, Math.min(width, height) * 0.025);
    const start = imagePointToClient(svg, {
      x: clamp(box.x - margin, 0, width),
      y: clamp(box.y - margin, 0, height)
    });
    const end = imagePointToClient(svg, {
      x: clamp(box.x + box.width + margin, 0, width),
      y: clamp(box.y + box.height + margin, 0, height)
    });

    const drawButton = findButtonByText(document, /^勾画$/);
    if (drawButton && !card.querySelector('.viewer-overlay.is-contour, .viewer-overlay.is-boxsam')) {
      drawButton.click();
      await new Promise((resolve) => window.setTimeout(resolve, 80));
    }

    const boxSamButton = findButtonByText(document, /^框选\+SAM$/);
    if (!boxSamButton || boxSamButton.disabled) {
      window.alert('当前没有可用的“框选+SAM”，请先进入勾画模式并选择勾画部位。');
      return;
    }

    button.disabled = true;
    button.dataset.running = '1';
    const originalText = button.textContent;
    button.textContent = '贴合中...';

    const originalSetPointerCapture = Element.prototype.setPointerCapture;
    Element.prototype.setPointerCapture = function patchedSetPointerCapture(pointerId) {
      try {
        return originalSetPointerCapture.call(this, pointerId);
      } catch {
        return undefined;
      }
    };

    try {
      boxSamButton.click();
      await new Promise((resolve) => window.setTimeout(resolve, 90));
      dispatchPointer(svg, 'pointerdown', start, 1);
      await new Promise((resolve) => window.setTimeout(resolve, 90));
      dispatchPointer(svg, 'pointermove', end, 1);
      await new Promise((resolve) => window.setTimeout(resolve, 30));
      dispatchPointer(svg, 'pointerup', end, 0);
    } finally {
      window.setTimeout(() => {
        Element.prototype.setPointerCapture = originalSetPointerCapture;
        if (button.isConnected) {
          delete button.dataset.running;
          button.disabled = false;
          button.textContent = originalText;
        }
      }, 1200);
    }
  };

  const ensureAutoFitButton = () => {
    const actions = Array.from(document.querySelectorAll('.inspector .inline-actions.wrap')).find((row) => {
      return Array.from(row.querySelectorAll('button')).some((button) => (button.textContent || '').trim() === '平滑轮廓');
    });
    if (!actions) return;

    let button = actions.querySelector('.cvi-auto-fit-contour');
    if (!button) {
      button = document.createElement('button');
      button.type = 'button';
      button.className = 'ghost-button cvi-auto-fit-contour';
      button.textContent = '自动贴合';
      button.title = '根据当前手工轮廓的外接框调用 SAM，重新贴合当前帧当前部位。';
      button.addEventListener('click', () => runAutoFitCurrentContour(button));

      const smoothButton = findButtonByText(actions, /^平滑轮廓$/);
      if (smoothButton) {
        actions.insertBefore(button, smoothButton);
      } else {
        actions.appendChild(button);
      }
    }

    const hasSelectedContour = Boolean(getSelectedContourContext());
    if (button.dataset.running === '1') {
      button.disabled = true;
      return;
    }
    button.disabled = !hasSelectedContour;
    button.title = hasSelectedContour
      ? '根据当前手工轮廓的外接框调用 SAM，重新贴合当前帧当前部位。'
      : '请先选中一个已经勾好的轮廓。';
  };

  const ensureReferenceStacks = () => {
    document.querySelectorAll('.viewer-grid').forEach((grid) => {
      let stack = grid.querySelector(':scope > .cvi-reference-stack');
      const directCards = Array.from(grid.children).filter((child) => child.classList?.contains('viewer-card'));

      if (!stack && directCards.length >= 2) {
        const referenceCard = directCards[1];
        stack = document.createElement('div');
        stack.className = 'cvi-reference-stack';
        grid.insertBefore(stack, referenceCard);
        stack.appendChild(referenceCard);
      } else if (stack && directCards.length >= 2) {
        const referenceCard = directCards[1];
        stack.insertBefore(referenceCard, stack.firstChild);
      }

      if (stack) updateReferenceAuxiliary(stack);
    });
  };

  const autoDetectEdEs = () => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const detectButton = buttons.find((button) => /自动检测 ED\/ES|正在自动检测 ED\/ES|自动检测 4CH 相位|正在自动检测相位|快速识别 ED\/ES|正在识别 ED\/ES|快速识别 4CH 相位|正在识别相位/.test(button.textContent || ''));
    if (!detectButton) return;

    const detectKind = /4CH/.test(detectButton.textContent || '') ? '4ch' : 'sax';
    const key = `${keys.autoEdEs}${detectKind}.${window.location.pathname}`;
    const group = detectButton.closest('.tool-group');
    const metricRows = group ? Array.from(group.querySelectorAll('.metric-row')) : [];
    const hasResolvedLabels = metricRows.some((row) => {
      const text = row.textContent || '';
      const value = row.querySelector('strong')?.textContent?.trim() || '';
      return /ED|ES|pre-A|max|min/.test(text) && value && !/^[—\s/-]+$/.test(value);
    });
    if (hasResolvedLabels) {
      storage.setItem(key, 'done');
      return;
    }

    const state = storage.getItem(key) || '';
    const now = Date.now();
    const pendingMatch = state.match(/^pending:(\d+)$/);
    if ((state === 'done' || state === 'manual-present') && !hasResolvedLabels) {
      storage.removeItem(key);
    }
    if (detectButton.disabled || /正在.*检测|正在识别/.test(detectButton.textContent || '')) {
      if (pendingMatch && now - Number(pendingMatch[1]) > 15000) {
        storage.removeItem(key);
      }
      return;
    }
    if (pendingMatch && now - Number(pendingMatch[1]) < 4000) {
      return;
    }

    storage.setItem(key, `pending:${now}`);
    window.setTimeout(() => {
      if (!detectButton.isConnected || detectButton.disabled) return;
      detectButton.click();
    }, 450);
  };

  const isTypingTarget = (target) => {
    if (!(target instanceof Element)) return false;
    if (target.closest('input, textarea, select, [contenteditable="true"], [contenteditable=""], .report-editor')) {
      return true;
    }
    return target instanceof HTMLElement && target.isContentEditable;
  };

  let inspectorTabKey = 'draw';

  const readInspectorTab = () => inspectorTabKey;

  const writeInspectorTab = (nextKey) => {
    inspectorTabKey = ['ai', 'research', 'report'].includes(nextKey) ? nextKey : 'draw';
  };

  /* ---- Inspector「报告生成」页签（2026-08-18 新增） ---- */
  const inspectorReportState = {
    studyId: null,
    loading: false,
    status: 'idle',
    message: '',
    caseId: '',
    dataset: '',
    reportText: '',
    renderKey: '',
  };
  const inspectorEvalCaseCache = {};

  const inferEvalDatasetCandidates = (sourcePath) => {
    const match = String(sourcePath || '').match(/\/home\/Larry\/data\/([^/]+)/);
    const root = match ? match[1] : '';
    const mapping = {
      CMR_ALL: ['CMR_ALL', 'new_CMR_ALL'],
      CMR_Chendu: ['new_CMR_Chendu', 'CMR_Chendu'],
      CMR_SCS: ['new_CMR_SCS', 'CMR_SCS'],
      CMR_YA: ['new_CMR_YA', 'CMR_YA'],
    };
    if (mapping[root]) return mapping[root];
    return root ? [root, `new_${root}`, 'CMR_ALL'] : ['CMR_ALL'];
  };

  const fetchEvalCaseList = async (dataset) => {
    if (Array.isArray(inspectorEvalCaseCache[dataset])) {
      return inspectorEvalCaseCache[dataset];
    }
    const response = await window.fetch(`/api/eval/cases?dataset=${encodeURIComponent(dataset)}`, {
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) {
      return null;
    }
    const cases = await response.json();
    if (!Array.isArray(cases)) return null;
    inspectorEvalCaseCache[dataset] = cases;
    return cases;
  };

  const renderInspectorReportPage = (container) => {
    const state = inspectorReportState;
    const key = [state.studyId, state.status, state.caseId, state.dataset, state.reportText.length, state.message].join('|');
    if (container.dataset.cviReportRenderKey === key) return;
    container.dataset.cviReportRenderKey = key;

    const linkRow = [
      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">',
      '<a href="/showcase/report" style="display:inline-block;padding:6px 12px;border-radius:6px;background:#a3e635;color:#1a2008;font-size:12px;font-weight:700;text-decoration:none">打开报告生成页</a>',
      '<a href="/evaluation" style="display:inline-block;padding:6px 12px;border-radius:6px;border:1px solid rgba(148,163,184,.25);color:#e8eaed;font-size:12px;font-weight:600;text-decoration:none">报告评分页</a>',
      '</div>',
    ].join('');

    let body = '';
    if (state.status === 'no-study') {
      body = '<div style="color:#9aa3ad;font-size:12px;line-height:1.7">先在左侧病例库打开一例 Study，这里会显示该病例的 AI 报告与报告生成入口。</div>';
    } else if (state.status === 'loading') {
      body = '<div style="color:#9aa3ad;font-size:12px;line-height:1.7">正在读取当前病例的 AI 报告…</div>';
    } else if (state.status === 'empty') {
      body = `<div style="color:#9aa3ad;font-size:12px;line-height:1.7">${state.message || '该病例暂无已生成的 AI 报告。'}</div>`;
    } else if (state.status === 'error') {
      body = `<div style="color:#ff9f9f;font-size:12px;line-height:1.7">${state.message || 'AI 报告读取失败。'}</div>`;
    } else if (state.status === 'ready') {
      body = [
        `<div style="color:#9aa3ad;font-size:11px;line-height:1.6;margin-bottom:6px">${state.dataset} · ${state.caseId}</div>`,
        `<div style="white-space:pre-wrap;color:#d5dbe3;font-size:12px;line-height:1.75;max-height:56vh;overflow:auto;border:1px solid rgba(148,163,184,.14);border-radius:8px;padding:10px 12px;background:rgba(255,255,255,.02)"></div>`,
      ].join('');
    }

    container.innerHTML = [
      '<strong style="display:block;font-size:13px;color:#f3f5f7;margin-bottom:6px">报告生成</strong>',
      body,
      linkRow,
    ].join('');

    if (state.status === 'ready') {
      const textBox = container.querySelector('[style*="white-space:pre-wrap"]');
      if (textBox) textBox.textContent = state.reportText;
    }
  };

  const loadInspectorReport = async (studyId) => {
    const state = inspectorReportState;
    state.studyId = studyId;
    state.loading = true;
    state.status = 'loading';
    state.caseId = '';
    state.dataset = '';
    state.reportText = '';
    state.message = '';
    const panel = document.querySelector('.inspector > .panel');
    const container = panel?.querySelector('.cvi-inspector-report-page');
    if (container instanceof HTMLElement) renderInspectorReportPage(container);

    try {
      const studyResponse = await window.fetch(`${CVI_API_BASE}/studies/${studyId}`, { headers: { Accept: 'application/json' } });
      if (!studyResponse.ok) throw new Error(`study ${studyResponse.status}`);
      const study = await studyResponse.json();
      // cvi-api 的 patient_id 形如「登记号：0000978064」，需要取出纯数字登记号再匹配。
      const registrationRaw = String(study?.patient_id || '').trim();
      const registrationMatch = registrationRaw.match(/00\d{8}/);
      const registrationId = registrationMatch ? registrationMatch[0] : registrationRaw;
      if (!registrationId) {
        state.status = 'empty';
        state.message = '当前 Study 缺少登记号，无法匹配 AI 报告。';
        return;
      }
      const datasets = inferEvalDatasetCandidates(study?.source_path);
      let matched = null;
      let sawList = false;
      for (const dataset of datasets) {
        const cases = await fetchEvalCaseList(dataset);
        if (!cases) continue;
        sawList = true;
        const hit = cases.find((item) => String(item?.id || '').startsWith(registrationId));
        if (hit) {
          matched = { dataset: hit.dataset || dataset, caseId: String(hit.id) };
          break;
        }
      }
      if (!matched) {
        state.status = 'empty';
        state.message = sawList
          ? `登记号 ${registrationId} 暂无已生成的 AI 报告，可前往报告生成页生成。`
          : '病例列表读取失败（可能未登录），请确认登录后重试。';
        return;
      }
      const detailResponse = await window.fetch(
        `/api/eval/cases/${encodeURIComponent(matched.dataset)}/${encodeURIComponent(matched.caseId)}?report_version=AI_LATEST`,
        { headers: { Accept: 'application/json' } },
      );
      if (!detailResponse.ok) throw new Error(`detail ${detailResponse.status}`);
      const detail = await detailResponse.json();
      const report = detail?.report;
      const text = typeof report === 'string' ? report : String(report?.text || detail?.report_text || '');
      if (!text.trim()) {
        state.status = 'empty';
        state.message = '该病例的 AI 报告内容为空。';
        state.dataset = matched.dataset;
        state.caseId = matched.caseId;
        return;
      }
      state.status = 'ready';
      state.dataset = matched.dataset;
      state.caseId = matched.caseId;
      state.reportText = text;
    } catch (error) {
      state.status = 'error';
      state.message = `AI 报告读取失败（${error instanceof Error ? error.message : '网络错误'}）。`;
    } finally {
      state.loading = false;
      const panelNow = document.querySelector('.inspector > .panel');
      const containerNow = panelNow?.querySelector('.cvi-inspector-report-page');
      if (containerNow instanceof HTMLElement) renderInspectorReportPage(containerNow);
    }
  };

  const ensureInspectorReportPage = (panel) => {
    if (!(panel instanceof HTMLElement)) return;
    let container = panel.querySelector(':scope > .cvi-inspector-report-page');
    if (!(container instanceof HTMLElement)) {
      container = document.createElement('section');
      container.className = 'cvi-inspector-report-page';
      container.style.cssText = 'display:flex;flex-direction:column;gap:6px;padding:10px 12px;border:1px solid rgba(148,163,184,.14);border-radius:10px;background:rgba(255,255,255,.02)';
      panel.appendChild(container);
    }
    container.dataset.cviInspectorGroup = 'report';
    container.hidden = inspectorTabKey !== 'report';
    if (container.hidden) return;

    const studyId = getCurrentStudyId();
    if (!studyId) {
      inspectorReportState.studyId = null;
      inspectorReportState.status = 'no-study';
      renderInspectorReportPage(container);
      return;
    }
    if (inspectorReportState.studyId !== studyId && !inspectorReportState.loading) {
      loadInspectorReport(studyId);
      return;
    }
    renderInspectorReportPage(container);
  };

  const getDirectInspectorBlocks = (panel, tabShell) => {
    return Array.from(panel.children).filter((child) => {
      return child instanceof HTMLElement
        && child !== tabShell
        && !child.classList.contains('cvi-inspector-pages');
    });
  };

  const getPrimaryText = (element, selector) => {
    return element.querySelector(selector)?.textContent?.trim() || '';
  };

  const hasButtonLabel = (element, pattern) => {
    return Array.from(element.querySelectorAll('button')).some((button) => {
      return pattern.test((button.textContent || '').trim());
    });
  };

  const DRAW_PANEL_TEXT_PATTERN = /勾画部位|勾画方式|轮廓修改|轮廓工具|工具属性|心动周期标记|手工 ED|手工 ES|LV ED|LV ES|RV ED|RV ES|心室相位|心房相位|左室内膜|左室外膜|右室腔|心外膜脂肪|一笔画线|点状勾画|毛刷|框选\+SAM|涂色\+SAM|AI勾画|点状微调|拖拽|微调模式/;
  const DRAW_PANEL_BUTTON_PATTERN = /^撤销$|^重做$|^生成当前轮廓$|^改为开口$|^闭合轮廓$|^平滑轮廓$|^简化控制点$|^删除末点$|^清空当前轮廓$|^清空当前帧全部轮廓$|^自动贴合$|^复制到上一层$|^复制到下一层$|^复制到上一相$|^复制到下一相$|^保存轮廓$/;
  const AI_PANEL_BUTTON_PATTERN = /^传播补全$|^AI 分割(?:\(全部相位\))?$|^暂停任务$|^传播到上一层$|^传播到下一层$|^传播到上一相$|^传播到下一相$|^自动检测 4CH 相位$|^自动检测 ED\/ES$|^快速识别 4CH 相位$|^快速识别 ED\/ES$|^当前相位设为 LV ED$|^当前相位设为 LV ES$|^当前相位设为 RV ED$|^当前相位设为 RV ES$|^当前设为 LA max$|^当前设为 LA pre-A$|^当前设为 LA min$|^当前设为 RA max$|^当前设为 RA pre-A$|^当前设为 RA min$|^当前相位设为 ED$|^当前相位设为 ES$/;

  const hideExperimentalFastDraft = (panel) => {
    panel.querySelectorAll('button').forEach((button) => {
      const label = (button.textContent || '').trim();
      if (!/^快速初稿(?:\(实验\))?$/.test(label)) return;
      button.hidden = true;
      button.style.display = 'none';
    });
  };

  const getInspectorBlockTitle = (block) => {
    if (!(block instanceof HTMLElement)) return '';
    return getPrimaryText(block, ':scope > strong');
  };

  const getDirectChildElements = (element) => {
    if (!(element instanceof HTMLElement)) return [];
    return Array.from(element.children).filter((child) => child instanceof HTMLElement);
  };

  const getInspectorSubsectionTitle = (element) => {
    if (!(element instanceof HTMLElement)) return '';
    return getPrimaryText(element, ':scope > strong');
  };

  const setForcedInspectorVisibility = (node, shouldShow) => {
    if (!(node instanceof HTMLElement)) return;

    if (shouldShow) {
      if (node.dataset.cviTabForceHidden === '1') {
        const previousDisplay = node.dataset.cviTabForceDisplay || '';
        if (previousDisplay) {
          node.style.display = previousDisplay;
        } else {
          node.style.removeProperty('display');
        }
        delete node.dataset.cviTabForceHidden;
        delete node.dataset.cviTabForceDisplay;
      }
      return;
    }

    if (node.dataset.cviTabForceHidden !== '1') {
      node.dataset.cviTabForceDisplay = node.style.display || '';
    }
    node.dataset.cviTabForceHidden = '1';
    node.style.setProperty('display', 'none', 'important');
  };

  const setForcedInspectorOrder = (node, orderValue) => {
    if (!(node instanceof HTMLElement)) return;
    if (orderValue == null) {
      if (node.dataset.cviTabForceOrder === '1') {
        const previousOrder = node.dataset.cviTabOrderValue || '';
        if (previousOrder) {
          node.style.order = previousOrder;
        } else {
          node.style.removeProperty('order');
        }
        delete node.dataset.cviTabForceOrder;
        delete node.dataset.cviTabOrderValue;
      }
      return;
    }

    if (node.dataset.cviTabForceOrder !== '1') {
      node.dataset.cviTabOrderValue = node.style.order || '';
    }
    node.dataset.cviTabForceOrder = '1';
    node.style.order = String(orderValue);
  };

  const enforceInspectorFocusedLayout = (panel, tabShell) => {
    const directBlocks = getDirectInspectorBlocks(panel, tabShell);
    directBlocks.forEach((block) => {
      setForcedInspectorVisibility(block, true);
      setForcedInspectorOrder(block, null);
      getDirectChildElements(block).forEach((child) => setForcedInspectorVisibility(child, true));
    });

    // 2026-08-18「报告生成」页签容器：显式跟随当前页签显隐，避免被上面的重置强制显示。
    const inspectorReportPage = panel.querySelector(':scope > .cvi-inspector-report-page');
    if (inspectorReportPage instanceof HTMLElement) {
      setForcedInspectorVisibility(inspectorReportPage, inspectorTabKey === 'report');
    }

    const syncTopActionBlock = (block) => {
      if (
        !block.matches('.inline-actions.wrap')
        || !hasButtonLabel(block, /^传播补全$|^AI 分割$|^保存轮廓$|^暂停任务$/)
      ) {
        return false;
      }

      let visibleCount = 0;
      block.querySelectorAll('button').forEach((button) => {
        if (!(button instanceof HTMLButtonElement)) return;
        const rawLabel = (button.textContent || '').trim();
        const groupKey = /^传播补全$|^AI 分割(?:\(全部相位\))?$|^暂停任务$/.test(rawLabel)
          ? 'ai'
          : /^保存轮廓$/.test(rawLabel)
            ? 'draw'
            : /^重算指标$/.test(rawLabel)
              ? 'research'
              : 'hidden';

        if (/^AI 分割/.test(rawLabel)) {
          button.textContent = 'AI 分割(全部相位)';
          button.title = '对当前序列执行全部相位 AI 分割。';
        }

        if (/^传播补全$|^AI 分割(?:\(全部相位\))?$|^保存轮廓$|^暂停任务$/.test(rawLabel)) {
          button.classList.remove('primary-button');
          if (!button.classList.contains('ghost-button')) {
            button.classList.add('ghost-button');
          }
        }

        const shouldShow = groupKey === inspectorTabKey;
        button.hidden = !shouldShow;
        if (shouldShow) visibleCount += 1;
      });

      setForcedInspectorVisibility(block, visibleCount > 0);
      setForcedInspectorOrder(block, inspectorTabKey === 'draw' ? 120 : inspectorTabKey === 'ai' ? 0 : null);
      return true;
    };

    const syncMixedDrawBlock = (block) => {
      const title = getInspectorBlockTitle(block);
      if (title !== '勾画部位' && title !== '轮廓工具') return false;

      let visibleCount = 0;
      getDirectChildElements(block).forEach((child) => {
        const childTitle = getInspectorSubsectionTitle(child);
        const childGroup = (
          (child.matches('.tool-subsection') && childTitle === '层间/相间传播')
          || (
            child.matches('.inline-actions.wrap')
            && hasButtonLabel(child, /^传播到上一层$|^传播到下一层$|^传播到上一相$|^传播到下一相$/)
          )
        ) ? 'ai' : 'draw';
        const shouldShow = inspectorTabKey === 'draw'
          ? childGroup === 'draw'
          : inspectorTabKey === 'ai'
            ? childGroup === 'ai'
            : false;
        setForcedInspectorVisibility(child, shouldShow);
        if (shouldShow) visibleCount += 1;
      });

      setForcedInspectorVisibility(block, visibleCount > 0);
      return true;
    };

    if (inspectorTabKey === 'draw') {
      directBlocks.forEach((block) => {
        if (syncTopActionBlock(block)) return;
        if (syncMixedDrawBlock(block)) return;
        const title = getInspectorBlockTitle(block);
        const isResearchBlock = block.matches('.metric-table-shell')
          || block.matches('.research-panel')
          || title === 'Volume Curve'
          || title === 'Polar Map';
        const isAiOnlyBlock = false;
        if (isResearchBlock || isAiOnlyBlock) {
          setForcedInspectorVisibility(block, false);
        }
      });
      return;
    }

    if (inspectorTabKey === 'ai') {
      directBlocks.forEach((block) => {
        if (syncTopActionBlock(block)) return;
        if (syncMixedDrawBlock(block)) return;
        const title = getInspectorBlockTitle(block);
        const shouldShow = block.matches('.status')
          || block.matches('.job-progress')
          || false;
        setForcedInspectorVisibility(block, shouldShow);
      });
      return;
    }

    // 2026-08-19：报告生成页签下隐藏除报告容器外的全部功能块，
    // 否则会落入下方科研指标兜底分支被强制显示。
    if (inspectorTabKey === 'report') {
      directBlocks.forEach((block) => {
        if (block.classList.contains('cvi-inspector-report-page')) return;
        setForcedInspectorVisibility(block, false);
      });
      return;
    }

    directBlocks.forEach((block) => {
      if (syncTopActionBlock(block)) return;
      if (syncMixedDrawBlock(block)) return;
      const title = getInspectorBlockTitle(block);
      const shouldShow = block.matches('.metric-table-shell')
        || block.matches('.research-panel')
        || title === 'Volume Curve'
        || title === 'Polar Map';
      setForcedInspectorVisibility(block, shouldShow);
    });
  };

  const classifyInspectorBlock = (block) => {
    if (!(block instanceof HTMLElement)) return 'draw';
    const text = (block.textContent || '').replace(/\s+/g, ' ').trim();

    if (block.classList.contains('cvi-inspector-report-page')) {
      return 'report';
    }

    if (block.dataset.cviProxySourceHidden === '1') {
      return 'hidden';
    }

    if (block.classList.contains('cvi-inspector-action-proxy')) {
      return block.dataset.cviInspectorGroup || 'draw';
    }

    if (
      block.matches('.research-panel')
      || block.querySelector('[data-cvi-research-card="1"]')
      || block.matches('.metric-table-shell')
    ) {
      return 'research';
    }

    if (DRAW_PANEL_TEXT_PATTERN.test(text)) {
      return 'draw';
    }

    const title = getPrimaryText(block, ':scope > strong');
    if (title === 'Volume Curve' || title === 'Polar Map') {
      return 'research';
    }

    if (title === 'LGE 阈值') {
      return 'draw';
    }

    if (title === '心动周期标记') {
      return 'draw';
    }

    if (block.matches('.job-progress')) {
      return 'ai';
    }

    if (block.matches('.status')) {
      if (/任务\s*#|传播补全|分割已完成|运行中|预计进度/.test(text)) {
        return 'ai';
      }
    }

    if (
      block.matches('.inline-actions.wrap')
      && hasButtonLabel(block, AI_PANEL_BUTTON_PATTERN)
    ) {
      return 'ai';
    }

    if (
      block.matches('.inline-actions.wrap')
      && hasButtonLabel(block, /^重算指标$/)
    ) {
      return 'research';
    }

    if (
      block.matches('.inline-actions.wrap')
      && hasButtonLabel(block, DRAW_PANEL_BUTTON_PATTERN)
    ) {
      return 'draw';
    }

    return 'draw';
  };

  const syncInspectorTabState = (tabShell) => {
    tabShell.querySelectorAll('[data-cvi-inspector-tab]').forEach((button) => {
      const isActive = button.getAttribute('data-cvi-inspector-tab') === inspectorTabKey;
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
    tabShell.querySelectorAll('.cvi-inspector-page').forEach((page) => {
      page.hidden = page.getAttribute('data-cvi-inspector-page') !== inspectorTabKey;
    });
  };

  const ensureInspectorTabbedLayout = () => {
    const panel = document.querySelector('.inspector > .panel');
    if (!(panel instanceof HTMLElement)) return;

    hideExperimentalFastDraft(panel);

    let tabShell = panel.querySelector(':scope > .cvi-inspector-tab-shell');
    if (!(tabShell instanceof HTMLElement)) {
      tabShell = document.createElement('section');
      tabShell.className = 'cvi-inspector-tab-shell';
      tabShell.innerHTML = [
        '<div class="cvi-inspector-tab-bar" role="tablist" aria-label="右侧面板切换" style="grid-template-columns:repeat(4,minmax(0,1fr))">',
        '<button type="button" class="cvi-inspector-tab" data-cvi-inspector-tab="draw">勾画面板</button>',
        '<button type="button" class="cvi-inspector-tab" data-cvi-inspector-tab="ai">传播与AI</button>',
        '<button type="button" class="cvi-inspector-tab" data-cvi-inspector-tab="research">科研指标</button>',
        '<button type="button" class="cvi-inspector-tab" data-cvi-inspector-tab="report">报告生成</button>',
        '</div>',
        '<div class="cvi-inspector-pages">',
        '<section class="cvi-inspector-page" data-cvi-inspector-page="draw"></section>',
        '<section class="cvi-inspector-page" data-cvi-inspector-page="ai"></section>',
        '<section class="cvi-inspector-page" data-cvi-inspector-page="research"></section>',
        '</div>'
      ].join('');
      panel.prepend(tabShell);

      tabShell.querySelectorAll('[data-cvi-inspector-tab]').forEach((button) => {
        button.addEventListener('click', () => {
          writeInspectorTab(button.getAttribute('data-cvi-inspector-tab') || 'draw');
          syncInspectorTabState(tabShell);
        });
      });
    }
    const pages = tabShell.querySelector('.cvi-inspector-pages');
    const drawPage = tabShell.querySelector('[data-cvi-inspector-page="draw"]');
    const aiPage = tabShell.querySelector('[data-cvi-inspector-page="ai"]');
    const researchPage = tabShell.querySelector('[data-cvi-inspector-page="research"]');
    if (!(pages instanceof HTMLElement) || !(drawPage instanceof HTMLElement) || !(aiPage instanceof HTMLElement) || !(researchPage instanceof HTMLElement)) return;

    getDirectInspectorBlocks(panel, tabShell).forEach((block) => {
      const groupKey = classifyInspectorBlock(block);
      block.dataset.cviInspectorGroup = groupKey;
      block.hidden = groupKey === 'hidden';
      if (groupKey === 'hidden') return;

      const targetPage = groupKey === 'ai'
        ? aiPage
        : groupKey === 'research'
          ? researchPage
          : drawPage;
      if (block.parentElement !== targetPage) {
        targetPage.appendChild(block);
      }
    });

    syncInspectorTabState(tabShell);
  };

  const syncInspectorProxySection = (panel, options) => {
    const {
      proxyKey,
      groupKey,
      title,
      buttonPattern
    } = options;
    const selector = `.cvi-inspector-action-proxy[data-cvi-proxy-key="${proxyKey}"]`;
    let section = panel.querySelector(selector);
    const sourceButtons = Array.from(panel.querySelectorAll('button')).filter((button) => {
      return !button.closest('.cvi-inspector-action-proxy')
        && buttonPattern.test((button.textContent || '').trim());
    });

    if (!sourceButtons.length) {
      section?.remove();
      return;
    }

    if (!(section instanceof HTMLElement)) {
      section = document.createElement('section');
      section.className = 'tool-group cvi-inspector-action-proxy';
      section.dataset.cviProxyKey = proxyKey;
      panel.appendChild(section);
    }

    section.dataset.cviInspectorGroup = groupKey;

    const signature = sourceButtons.map((button) => {
      return [
        (button.textContent || '').trim(),
        button.className || '',
        button.disabled ? '1' : '0',
        button.title || ''
      ].join('|');
    }).join('::');

    if (section.dataset.signature !== signature) {
      section.dataset.signature = signature;
      section.innerHTML = '';

      const actions = document.createElement('div');
      actions.className = 'inline-actions wrap';

      sourceButtons.forEach((sourceButton) => {
        const proxyButton = document.createElement('button');
        proxyButton.type = 'button';
        proxyButton.className = sourceButton.className;
        proxyButton.textContent = (sourceButton.textContent || '').trim();
        proxyButton.title = sourceButton.title || '';
        proxyButton.disabled = sourceButton.disabled;
        proxyButton.addEventListener('click', () => sourceButton.click());
        actions.appendChild(proxyButton);
      });

      if (title) {
        const heading = document.createElement('strong');
        heading.textContent = title;
        section.append(heading);
      }
      section.append(actions);
    } else {
      Array.from(section.querySelectorAll('button')).forEach((button, index) => {
        const sourceButton = sourceButtons[index];
        if (!sourceButton) return;
        button.disabled = sourceButton.disabled;
        button.className = sourceButton.className;
        button.title = sourceButton.title || '';
        button.textContent = (sourceButton.textContent || '').trim();
      });
    }

    const sourceRows = new Set(
      sourceButtons
        .map((button) => button.closest('.inline-actions.wrap'))
        .filter((row) => row instanceof HTMLElement)
    );

    sourceRows.forEach((row) => {
      row.dataset.cviProxySourceHidden = '1';
      row.hidden = true;
      row.style.display = 'none';
    });
  };

  const ensureInspectorActionArchiving = () => {
    const panel = document.querySelector('.inspector > .panel');
    if (!(panel instanceof HTMLElement)) return;

    syncInspectorProxySection(panel, {
      proxyKey: 'draw-save',
      groupKey: 'draw',
      title: '',
      buttonPattern: /^保存轮廓$/
    });

    syncInspectorProxySection(panel, {
      proxyKey: 'ai-actions',
      groupKey: 'ai',
      title: '',
      buttonPattern: /^传播补全$|^AI 分割$|^传播到上一层$|^传播到下一层$|^传播到上一相$|^传播到下一相$/
    });

    syncInspectorProxySection(panel, {
      proxyKey: 'research-metric',
      groupKey: 'research',
      title: '',
      buttonPattern: /^重算指标$/
    });

    panel.querySelectorAll('.cvi-inspector-action-proxy').forEach((section) => {
      const proxyKey = section.getAttribute('data-cvi-proxy-key') || '';
      if (!['draw-save', 'ai-actions', 'research-metric'].includes(proxyKey)) {
        section.remove();
      }
    });

    const tabShell = panel.querySelector(':scope > .cvi-inspector-tab-shell');
    if (tabShell instanceof HTMLElement) {
      ensureInspectorTabbedLayout();
      syncInspectorTabState(tabShell);
    }
  };

  const rollbackInspectorTabbedLayout = () => {
    const panel = document.querySelector('.inspector > .panel');
    if (!(panel instanceof HTMLElement)) return;

    const tabShell = panel.querySelector(':scope > .cvi-inspector-tab-shell');
    if (tabShell instanceof HTMLElement && tabShell.querySelector('.cvi-inspector-pages')) {
      tabShell.querySelectorAll('.cvi-inspector-page').forEach((page) => {
        Array.from(page.children).forEach((child) => {
          if (child instanceof HTMLElement) {
            child.hidden = false;
            panel.appendChild(child);
          }
        });
      });
      tabShell.remove();
    }

    panel.querySelectorAll('.cvi-inspector-action-proxy').forEach((node) => node.remove());

    panel.querySelectorAll('[data-cvi-proxy-source-hidden="1"]').forEach((node) => {
      if (!(node instanceof HTMLElement)) return;
      node.hidden = false;
      node.style.removeProperty('display');
      delete node.dataset.cviProxySourceHidden;
    });

    panel.querySelectorAll('[data-cvi-inspector-group]').forEach((node) => {
      if (!(node instanceof HTMLElement)) return;
      node.hidden = false;
      delete node.dataset.cviInspectorGroup;
    });

    panel.querySelectorAll('[data-cvi-inspector-button-group]').forEach((node) => {
      if (!(node instanceof HTMLElement)) return;
      node.hidden = false;
      delete node.dataset.cviInspectorButtonGroup;
    });
  };

  const classifyInspectorButton = (button) => {
    if (!(button instanceof HTMLButtonElement)) return 'draw';
    const label = (button.textContent || '').trim();

    if (/^快速初稿(?:\(实验\))?$/.test(label)) return 'hidden';
    if (DRAW_PANEL_BUTTON_PATTERN.test(label)) return 'draw';
    if (AI_PANEL_BUTTON_PATTERN.test(label)) return 'ai';
    if (/^重算指标$/.test(label)) return 'research';
    return 'draw';
  };

  const syncInspectorSafeTabs = (tabShell, panel) => {
    tabShell.querySelectorAll('[data-cvi-inspector-tab]').forEach((button) => {
      const isActive = button.getAttribute('data-cvi-inspector-tab') === inspectorTabKey;
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });

    getDirectInspectorBlocks(panel, tabShell).forEach((block) => {
      if (block.matches('.inline-actions.wrap')) {
        let visibleCount = 0;
        block.querySelectorAll('button').forEach((button) => {
          if (!(button instanceof HTMLButtonElement)) return;
          const groupKey = classifyInspectorButton(button);
          button.dataset.cviInspectorButtonGroup = groupKey;
          const shouldShow = groupKey !== 'hidden' && groupKey === inspectorTabKey;
          button.hidden = !shouldShow;
          if (shouldShow) visibleCount += 1;
        });
        block.hidden = visibleCount === 0;
        return;
      }

      const groupKey = classifyInspectorBlock(block);
      block.dataset.cviInspectorGroup = groupKey;
      block.hidden = groupKey === 'hidden' || groupKey !== inspectorTabKey;
    });

    enforceInspectorFocusedLayout(panel, tabShell);
  };

  const ensureInspectorSafeTabs = () => {
    const panel = document.querySelector('.inspector > .panel');
    if (!(panel instanceof HTMLElement)) return;

    hideExperimentalFastDraft(panel);

    let tabShell = panel.querySelector(':scope > .cvi-inspector-tab-shell');
    if (!(tabShell instanceof HTMLElement)) {
      tabShell = document.createElement('section');
      tabShell.className = 'cvi-inspector-tab-shell';
      tabShell.innerHTML = [
        '<div class="cvi-inspector-tab-bar" role="tablist" aria-label="右侧面板切换">',
        '<button type="button" class="cvi-inspector-tab" data-cvi-inspector-tab="draw">勾画面板</button>',
        '<button type="button" class="cvi-inspector-tab" data-cvi-inspector-tab="ai">传播与AI</button>',
        '<button type="button" class="cvi-inspector-tab" data-cvi-inspector-tab="research">科研指标</button>',
        '</div>'
      ].join('');
      panel.prepend(tabShell);

      tabShell.querySelectorAll('[data-cvi-inspector-tab]').forEach((button) => {
        button.addEventListener('click', () => {
          writeInspectorTab(button.getAttribute('data-cvi-inspector-tab') || 'draw');
          syncInspectorSafeTabs(tabShell, panel);
          ensureInspectorReportPage(panel);
        });
      });
    }

    // 2026-08-18：为既有三页签外壳补齐「报告生成」页签（老页面可能已建好旧外壳）。
    const tabBar = tabShell.querySelector('.cvi-inspector-tab-bar');
    if (tabBar instanceof HTMLElement) {
      tabBar.style.gridTemplateColumns = 'repeat(4, minmax(0, 1fr))';
      if (!tabBar.querySelector('[data-cvi-inspector-tab="report"]')) {
        const reportButton = document.createElement('button');
        reportButton.type = 'button';
        reportButton.className = 'cvi-inspector-tab';
        reportButton.setAttribute('data-cvi-inspector-tab', 'report');
        reportButton.textContent = '报告生成';
        reportButton.addEventListener('click', () => {
          writeInspectorTab('report');
          syncInspectorSafeTabs(tabShell, panel);
          ensureInspectorReportPage(panel);
        });
        tabBar.appendChild(reportButton);
      }
    }

    syncInspectorSafeTabs(tabShell, panel);
    ensureInspectorReportPage(panel);
  };

  const getNavigatorInput = (labelText) => {
    const labels = Array.from(document.querySelectorAll('.navigator-bar label'));
    const matchedLabel = labels.find((label) => {
      const labelNode = Array.from(label.childNodes).find((node) => node.nodeType === Node.TEXT_NODE);
      const text = (labelNode?.textContent || label.textContent || '').trim();
      return text.startsWith(labelText);
    });
    return matchedLabel?.querySelector('input[type="range"]') || null;
  };

  const stepNavigatorInput = (input, delta) => {
    if (!input || input.disabled) return false;
    const current = Number(input.value);
    const min = Number(input.min || 0);
    const max = Number(input.max || 0);
    const step = Number(input.step || 1) || 1;
    const next = clamp(current + delta * step, min, max);
    if (!Number.isFinite(next) || next === current) return false;
    const valueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
    if (valueSetter) {
      valueSetter.call(input, String(next));
    } else {
      input.value = String(next);
    }
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  };

  const annotationOriginMeta = {
    manual: { label: '手工', tone: 'manual', icon: '手' },
    ai: { label: 'AI', tone: 'ai', icon: 'AI' },
    propagate: { label: '传播', tone: 'propagate', icon: '传' }
  };

  const normalizeAnnotationOrigin = (origin) => {
    switch (String(origin || '').toLowerCase()) {
      case 'manual':
      case 'manual_refine':
      case 'copy':
      case 'legacy':
        return 'manual';
      case 'ai':
      case 'fast':
        return 'ai';
      case 'propagate':
        return 'propagate';
      default:
        return '';
    }
  };

  const formatAnnotationTime = (value) => {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, '0'),
      String(date.getDate()).padStart(2, '0')
    ].join('-') + ' ' + [
      String(date.getHours()).padStart(2, '0'),
      String(date.getMinutes()).padStart(2, '0')
    ].join(':');
  };

  const getActiveContourPayload = () => {
    return window.__cviContourPayload || null;
  };

  const getActiveFrameMeta = () => {
    const payload = getActiveContourPayload();
    if (!payload || typeof payload !== 'object') return null;
    const sliceInput = getNavigatorInput('Slice');
    const phaseInput = getNavigatorInput('Phase');
    const sliceIndex = Number(sliceInput?.value || 0);
    const phaseIndex = Number(phaseInput?.value || 0);
    const frameKey = `${sliceIndex}:${phaseIndex}`;
    const frameMeta = payload.frame_meta?.[frameKey];
    return {
      payload,
      frameKey,
      frameMeta: frameMeta || null,
      topMeta: payload.annotation_meta || {}
    };
  };

  const ensureAnnotationOverlay = () => {
    const mainStage = document.querySelector('.viewer-grid > .viewer-card:first-child .viewer-stage');
    if (!(mainStage instanceof HTMLElement)) return;

    let overlay = mainStage.querySelector('.cvi-annotation-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = 'cvi-annotation-overlay';
      mainStage.appendChild(overlay);
    }

    const active = getActiveFrameMeta();
    if (!active) {
      overlay.innerHTML = '';
      overlay.hidden = true;
      return;
    }

    const meta = active.frameMeta || active.topMeta || {};
    const originKey = normalizeAnnotationOrigin(meta.origin || active.topMeta.origin) || 'manual';
    const originInfo = annotationOriginMeta[originKey] || annotationOriginMeta.manual;
    const createdBy = meta.created_by_username || active.topMeta.created_by_username || '未知';
    const updatedBy = meta.updated_by_username || active.topMeta.updated_by_username || createdBy || '未知';
    const createdAt = formatAnnotationTime(meta.created_at || active.topMeta.created_at);
    const updatedAt = formatAnnotationTime(meta.updated_at || active.topMeta.updated_at);
    const sourceFrame = meta.source_frame ? String(meta.source_frame).split(':') : null;

    overlay.hidden = false;
    overlay.innerHTML = [
      `<div class=\"cvi-annotation-overlay__badge is-${originInfo.tone}\">${originInfo.label}</div>`,
      `<div>创建：${createdBy} · ${createdAt}</div>`,
      `<div>更新：${updatedBy} · ${updatedAt}</div>`,
      sourceFrame && sourceFrame.length === 2
        ? `<div>来源帧：S${Number(sourceFrame[0]) + 1} / P${Number(sourceFrame[1]) + 1}</div>`
        : ''
    ].join('');
  };

  const ensureMatrixSourceBadges = () => {
    const payload = getActiveContourPayload();
    const frameMeta = payload?.frame_meta || {};

    document.querySelectorAll('.matrix-result-tag').forEach((tag) => {
      if (tag instanceof HTMLElement) tag.style.display = 'none';
    });

    document.querySelectorAll('[data-cvi-frame-cell="1"]').forEach((cell) => {
      if (!(cell instanceof HTMLElement)) return;
      const sliceIndex = Number(cell.getAttribute('data-cvi-slice-index'));
      const phaseIndex = Number(cell.getAttribute('data-cvi-phase-index'));
      const key = `${sliceIndex}:${phaseIndex}`;
      const hasContours = cell.classList.contains('has-contours');
      const meta = frameMeta[key] || (hasContours ? payload?.annotation_meta || null : null);
      const originKey = normalizeAnnotationOrigin(meta?.origin);
      const originInfo = annotationOriginMeta[originKey] || null;

      cell.dataset.cviOrigin = originInfo?.tone || '';
      const previousBadge = cell.querySelector('.cvi-origin-badge, .cvi-origin-dot');
      if (previousBadge) previousBadge.remove();
      if (!hasContours || !originInfo) return;

      const badge = document.createElement('span');
      badge.className = `cvi-origin-badge is-${originInfo.tone}`;
      badge.textContent = originInfo.icon;
      badge.title = [
        `来源：${originInfo.label}`,
        `更新人：${meta?.updated_by_username || payload?.annotation_meta?.updated_by_username || '未知'}`,
        `更新时间：${formatAnnotationTime(meta?.updated_at || payload?.annotation_meta?.updated_at)}`
      ].join('\\n');
      cell.appendChild(badge);
    });
  };

  const ensureMatrixSourceLegend = () => {
    const legend = document.querySelector('.stack-matrix .matrix-legend');
    if (!(legend instanceof HTMLElement)) return;

    legend.querySelectorAll('.matrix-legend-badge.is-manual, .matrix-legend-badge.is-ai, .matrix-legend-badge.is-propagate, .matrix-legend-badge.is-fast').forEach((badge) => {
      const item = badge.closest('span');
      if (item instanceof HTMLElement) item.style.display = 'none';
    });

    if (legend.querySelector('[data-cvi-origin-legend="1"]')) return;

    [
      ['manual', '手工'],
      ['ai', 'AI'],
      ['propagate', '传播']
    ].forEach(([originKey, label]) => {
      const item = document.createElement('span');
      item.setAttribute('data-cvi-origin-legend', '1');
      item.innerHTML = `<i class=\"cvi-origin-badge is-${annotationOriginMeta[originKey].tone}\">${annotationOriginMeta[originKey].icon}</i>${label}`;
      legend.appendChild(item);
    });
  };

  const ensureMatrixCornerLayout = () => {
    const corner = document.querySelector('.stack-matrix .matrix-corner');
    if (!(corner instanceof HTMLElement)) return;

    const defaultLabel = corner.querySelector(':scope > span');
    if (defaultLabel instanceof HTMLElement) defaultLabel.hidden = true;

    let split = corner.querySelector('.cvi-matrix-corner-split');
    if (!(split instanceof HTMLElement)) {
      split = document.createElement('div');
      split.className = 'cvi-matrix-corner-split';
      split.innerHTML = '<span class="cvi-matrix-corner-label is-s">S</span><span class="cvi-matrix-corner-label is-p">P</span>';
      corner.prepend(split);
    }

    corner.querySelectorAll('.matrix-corner-tools .matrix-axis-toggle').forEach((button, index) => {
      if (!(button instanceof HTMLElement)) return;
      button.dataset.axisMaster = index === 0 ? 'slice' : 'phase';
      button.textContent = button.classList.contains('is-off') ? '开' : '关';
    });
  };

  const hiddenProtocolPhasePages = new Set(['patientdata', 'report', 'seriesoverview', 'viewer']);

  const normalizeProtocolLabel = (value) => {
    return String(value || '').replace(/\s+/g, '').trim().toLowerCase();
  };

  const getProtocolItemLabel = (item) => {
    if (!(item instanceof HTMLElement)) return '';
    const directLabel = item.querySelector('.protocol-item-label')?.textContent?.trim();
    if (directLabel) return directLabel;

    const heading = item.querySelector('strong, h2, h3, h4')?.textContent?.trim();
    if (heading) return heading;

    const text = (item.textContent || '')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)[0];
    return text || '';
  };

  const isVisibleElement = (element) => {
    return element instanceof HTMLElement && element.isConnected && element.getClientRects().length > 0;
  };

  const getActiveProtocolLabel = () => {
    const activeItems = Array.from(document.querySelectorAll('.protocol-item.is-active'));
    const visibleActiveItem = activeItems.find(isVisibleElement) || activeItems[0];
    const activeLabel = getProtocolItemLabel(visibleActiveItem);
    if (activeLabel) return activeLabel;

    const centerHeadings = Array.from(document.querySelectorAll(
      '.center-pane .panel-title h2, .center-pane .panel > h2, .center-pane section.panel h2'
    ));
    const visibleHeading = centerHeadings.find((node) => {
      return isVisibleElement(node) && hiddenProtocolPhasePages.has(normalizeProtocolLabel(node.textContent));
    });
    return visibleHeading?.textContent?.trim() || '';
  };

  const shouldHideProtocolPhaseControls = () => {
    const visibleOverviewGrid = Array.from(document.querySelectorAll('.overview-grid')).find(isVisibleElement);
    if (visibleOverviewGrid) return true;
    return hiddenProtocolPhasePages.has(normalizeProtocolLabel(getActiveProtocolLabel()));
  };

  const ensureProtocolPhaseControlsVisibility = () => {
    const shouldHide = shouldHideProtocolPhaseControls();
    document.documentElement.dataset.cviHideProtocolPhaseControls = shouldHide ? '1' : '0';

    document.querySelectorAll('.navigator-bar, .stack-matrix').forEach((section) => {
      if (!(section instanceof HTMLElement)) return;
      section.hidden = shouldHide;
      if (shouldHide) {
        section.style.display = 'none';
      } else {
        section.style.removeProperty('display');
      }
    });
  };

  const safeEnsureProtocolPhaseControlsVisibility = () => {
    try {
      ensureProtocolPhaseControlsVisibility();
    } catch {}
  };

  const flushContourAutoSaveIfNeeded = () => {
    const key = typeof window.__cviGetContourAutoSaveKey === 'function'
      ? window.__cviGetContourAutoSaveKey()
      : window.__cviLastContourAutoSaveKey;
    if (!key || typeof window.__cviFlushContourAutoSaveByKey !== 'function') return;
    window.__cviFlushContourAutoSaveByKey(key).catch(() => {});
  };

  const ensureAutosaveFlushHooks = () => {
    if (!document.body || document.body.dataset.cviAutosaveFlushBound === '1') return;
    document.body.dataset.cviAutosaveFlushBound = '1';

    document.addEventListener('pointerdown', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const actionButton = target.closest('button');
      if (actionButton) {
        const label = (actionButton.textContent || '').trim();
        if (
          /^(左房|右房|左室内膜|左室外膜|心室外膜|脂肪壁层|脂肪ROI\(旧\)|排除区|右室腔|右室|一笔画线|点状勾画|毛刷|框选\+SAM|涂色\+SAM|AI勾画|点状微调|拖拽|微调模式|撤销|重做|生成当前轮廓|闭合轮廓|改为开口|清空当前轮廓|清空当前帧全部轮廓|清空全部轮廓)$/.test(label)
        ) {
          clearDrawContourPreviews();
        }
      }
      if (
        target.closest('.navigator-bar input[type="range"]') ||
        target.closest('.stack-matrix .matrix-cell') ||
        target.closest('.stack-matrix .matrix-head') ||
        target.closest('.stack-matrix .matrix-side') ||
        target.closest('.stack-matrix .matrix-axis-toggle')
      ) {
        clearDrawContourPreviews();
        flushContourAutoSaveIfNeeded();
      }
    }, true);

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') flushContourAutoSaveIfNeeded();
    });

    window.addEventListener('beforeunload', flushContourAutoSaveIfNeeded);
  };

  const activeResearchFocus = {
    key: '',
    sources: [],
    contourKeys: []
  };

  const frameSourceKey = (sliceIndex, phaseIndex) => `${Number(sliceIndex)}:${Number(phaseIndex)}`;

  const parseResearchCardData = (card) => {
    if (!(card instanceof HTMLElement)) return null;
    const rawSources = card.dataset.cviSources || '[]';
    const rawContours = card.dataset.cviContours || '';
    let sources;
    try {
      sources = JSON.parse(rawSources);
    } catch {
      sources = [];
    }
    const normalizedSources = Array.isArray(sources)
      ? sources
          .map((source) => {
            const sliceIndex = Number(source?.slice_index);
            const phaseIndex = Number(source?.phase_index);
            if (!Number.isInteger(sliceIndex) || !Number.isInteger(phaseIndex)) return null;
            return {
              slice_index: sliceIndex,
              phase_index: phaseIndex,
              contour_keys: Array.isArray(source?.contour_keys)
                ? source.contour_keys.map((key) => String(key)).filter(Boolean)
                : []
            };
          })
          .filter(Boolean)
      : [];
    const contourKeys = (card.dataset.cviContours || '')
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean);
    return {
      key: [
        window.location.pathname,
        card.dataset.cviStageKey || '',
        card.dataset.cviRegionKey || '',
        rawSources,
        rawContours
      ].join('::'),
      sources: normalizedSources,
      contourKeys
    };
  };

  const clearResearchContourFocus = () => {
    document.querySelectorAll('.viewer-overlay .contour').forEach((node) => {
      node.classList.remove('cvi-research-hit', 'cvi-research-dim');
    });
  };

  const applyResearchFocusVisuals = () => {
    const focusKey = activeResearchFocus.key;
    const sourceSet = new Set(activeResearchFocus.sources.map((source) => frameSourceKey(source.slice_index, source.phase_index)));
    const primarySource = activeResearchFocus.sources[0];

    document.querySelectorAll('[data-cvi-research-card="1"]').forEach((card) => {
      const cardData = parseResearchCardData(card);
      const isActive = focusKey && cardData?.key === focusKey;
      card.classList.toggle('is-research-active', Boolean(isActive));
    });

    document.querySelectorAll('[data-cvi-frame-cell="1"]').forEach((cell) => {
      const sliceIndex = Number(cell.getAttribute('data-cvi-slice-index'));
      const phaseIndex = Number(cell.getAttribute('data-cvi-phase-index'));
      const isMatch = sourceSet.has(frameSourceKey(sliceIndex, phaseIndex));
      const isPrimary = Boolean(
        isMatch
        && primarySource
        && sliceIndex === Number(primarySource.slice_index)
        && phaseIndex === Number(primarySource.phase_index)
      );
      cell.classList.toggle('is-research-source', isMatch);
      cell.classList.toggle('is-research-primary', isPrimary);
    });

    const contourSet = new Set(activeResearchFocus.contourKeys);
    if (!contourSet.size) {
      clearResearchContourFocus();
      return;
    }

    document.querySelectorAll('.viewer-overlay .contour').forEach((node) => {
      const contourKey = Array.from(node.classList).find((className) => {
        return className.startsWith('contour-') && className !== 'contour';
      })?.replace(/^contour-/, '');
      const isHit = contourKey ? contourSet.has(contourKey) : false;
      node.classList.toggle('cvi-research-hit', isHit);
      node.classList.toggle('cvi-research-dim', !isHit);
    });
  };

  const clearResearchFocus = () => {
    activeResearchFocus.key = '';
    activeResearchFocus.sources = [];
    activeResearchFocus.contourKeys = [];
    applyResearchFocusVisuals();
  };

  const jumpToResearchSource = (sources) => {
    if (!Array.isArray(sources) || !sources.length) return false;
    const primary = sources[0];
    const selector = [
      '[data-cvi-frame-cell="1"]',
      `[data-cvi-slice-index="${Number(primary.slice_index)}"]`,
      `[data-cvi-phase-index="${Number(primary.phase_index)}"]`
    ].join('');
    const cell = document.querySelector(selector);
    if (!(cell instanceof HTMLElement)) return false;
    cell.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    cell.click();
    return true;
  };

  const focusResearchCard = (card) => {
    const data = parseResearchCardData(card);
    if (!data || !data.sources.length) return;
    if (activeResearchFocus.key === data.key) {
      clearResearchFocus();
      return;
    }
    activeResearchFocus.key = data.key;
    activeResearchFocus.sources = data.sources;
    activeResearchFocus.contourKeys = data.contourKeys;
    applyResearchFocusVisuals();
    jumpToResearchSource(data.sources);
    window.setTimeout(applyResearchFocusVisuals, 120);
  };

  const formatTrackingValue = (value, digits = 3) => {
    if (value == null || value === '') return '—';
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return String(value);
    return numeric.toFixed(digits).replace(/\.?0+$/, '');
  };

  const escapeHtml = (value) => String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');

  const trackingRegionLabel = (key) => {
    const labels = {
      endo: '心内膜',
      epi: '心外膜',
      myocardium: '心肌',
      la: '左房'
    };
    return labels[key] || key;
  };

  const trackingSvg = (pairs, regionKey) => {
    const values = (Array.isArray(pairs) ? pairs : [])
      .map((pair) => pair?.regions?.[regionKey]?.dice)
      .filter((value) => Number.isFinite(Number(value)))
      .map(Number);
    if (values.length < 2) return '';
    const width = 220;
    const height = 54;
    const min = Math.min(0.5, ...values);
    const max = Math.max(1, ...values);
    const span = Math.max(0.001, max - min);
    const points = values.map((value, index) => {
      const x = values.length === 1 ? 0 : (index / (values.length - 1)) * width;
      const y = height - ((value - min) / span) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return [
      `<svg class="cvi-tracking-sparkline" viewBox="0 0 ${width} ${height}" role="img" aria-label="${trackingRegionLabel(regionKey)} Dice 曲线">`,
      '<line x1="0" y1="53" x2="220" y2="53" stroke="rgba(148,163,184,.4)" stroke-width="1"/>',
      `<polyline fill="none" stroke="currentColor" stroke-width="2" points="${points}"/>`,
      '</svg>'
    ].join('');
  };

  const mainCineRole = () => {
    const title = document.querySelector('.center-pane .viewer-grid > .viewer-card:first-child .viewer-head h3')
      ?.textContent?.trim() || '';
    if (title.includes('4CH')) return 'cine_lax_4ch';
    if (title.includes('3CH')) return 'cine_lax_3ch';
    if (title.includes('2CH')) return 'cine_lax_2ch';
    if (title.includes('SAX')) return 'cine_sax';
    return '';
  };

  const mainCineSeries = () => {
    const role = mainCineRole();
    if (!role) return null;
    const candidates = (window.__cviSeriesCache?.series || []).filter((item) => item?.role === role);
    if (!candidates.length) return null;
    const subtitle = document.querySelector('.center-pane .viewer-grid > .viewer-card:first-child .viewer-head p')
      ?.textContent?.trim() || '';
    const descriptionMatch = candidates.find((item) => item.description && subtitle.includes(item.description));
    if (descriptionMatch) return descriptionMatch;
    const payloadMatch = candidates.find((item) => (
      window.__cviContourPayloadByKey?.[`${item.id}:function`]
    ));
    return payloadMatch || candidates[0];
  };

  const activeFunctionSeries = () => {
    const activeKey = typeof window.__cviGetContourAutoSaveKey === 'function'
      ? String(window.__cviGetContourAutoSaveKey() || '')
      : '';
    const activeMatch = activeKey.match(/^function:(\d+)$/);
    if (activeMatch) {
      const activeId = Number(activeMatch[1]);
      const cached = (window.__cviSeriesCache?.series || []).find((item) => Number(item?.id) === activeId);
      if (cached) return cached;
      return { id: activeId, role: mainCineRole() || 'cine_sax' };
    }
    const series = mainCineSeries();
    return series && String(series.role || '').startsWith('cine_') ? series : null;
  };

  const fatThresholdState = {
    identity: '',
    enabled: false,
    fillVisible: false,
    fillSeriesId: null,
    lower: 0,
    upper: 255,
    preview: null,
    loading: false,
    saving: false,
    dragging: false,
    dirty: false,
    drafts: new Map(),
    status: '',
    timer: null
  };

  const rememberFatThresholdDraft = () => {
    if (!fatThresholdState.identity) return;
    fatThresholdState.drafts.set(fatThresholdState.identity, {
      enabled: Boolean(fatThresholdState.enabled),
      lower: Number(fatThresholdState.lower),
      upper: Number(fatThresholdState.upper)
    });
    fatThresholdState.dirty = true;
  };

  const activeProtocolKey = () => normalizeProtocolLabel(getActiveProtocolLabel());
  const isFunctionProtocolActive = () => ['functionsax', 'function4ch'].includes(activeProtocolKey());
  const isLgeProtocolActive = () => activeProtocolKey() === 'tissuelge';

  const activeFunctionContourPayload = (series) => {
    const keyed = window.__cviContourPayloadByKey?.[`${Number(series?.id)}:function`];
    if (keyed) return keyed;
    const active = window.__cviContourPayload;
    return Number(active?.series_id) === Number(series?.id) && active?.module === 'function' ? active : null;
  };

  const refreshFunctionContourPayload = async (seriesId) => {
    const response = await window.fetch(`${CVI_API_BASE}/contours/${Number(seriesId)}?module=function`, {
      headers: { Accept: 'application/json' }
    });
    if (!response.ok) throw new Error(`轮廓刷新失败：HTTP ${response.status}`);
    const payload = await response.json();
    window.__cviContourPayload = payload;
    window.__cviContourPayloadByKey = window.__cviContourPayloadByKey || {};
    window.__cviContourPayloadByKey[`${Number(seriesId)}:function`] = payload;
    return payload;
  };

  const currentViewerContourKeys = () => {
    const keys = new Set();
    const viewer = document.querySelector('.center-pane .viewer-grid > .viewer-card:first-child .viewer-overlay');
    viewer?.querySelectorAll('.contour').forEach((node) => {
      Array.from(node.classList).forEach((className) => {
        if (className.startsWith('contour-') && className !== 'contour') {
          keys.add(className.replace(/^contour-/, ''));
        }
      });
    });
    return keys;
  };

  const activeFatThresholdFrame = () => {
    if (!isFunctionProtocolActive()) return null;
    const series = activeFunctionSeries();
    if (!series) return null;
    const sliceIndex = Number(getNavigatorInput('Slice')?.value || 0);
    const phaseIndex = Number(getNavigatorInput('Phase')?.value || 0);
    const frameKey = `${sliceIndex}:${phaseIndex}`;
    const payload = activeFunctionContourPayload(series);
    const frame = payload?.frames?.[frameKey] || null;
    return { series, sliceIndex, phaseIndex, frameKey, payload, frame, visibleContourKeys: currentViewerContourKeys() };
  };

  const contourHasPoints = (contour) => Array.isArray(contour?.points) && contour.points.length >= 3;

  const fatCandidateContourStatus = (frame, visibleContourKeys = new Set()) => {
    const hasContour = (key) => contourHasPoints(frame?.[key]) || visibleContourKeys.has(key);
    const legacyFat = hasContour('fat');
    const fatOuter = hasContour('fat_outer');
    const ventricularEpi = hasContour('ventricular_epi');
    const epiFallback = hasContour('epi');
    return {
      legacyFat,
      fatOuter,
      ventricularEpi,
      epiFallback,
      ready: legacyFat || (fatOuter && (ventricularEpi || epiFallback))
    };
  };

  const hasFatCandidateContours = (frame, visibleContourKeys) => {
    return fatCandidateContourStatus(frame, visibleContourKeys).ready;
  };

  const removeFatThresholdOverlay = () => {
    document.querySelectorAll('.cvi-fat-threshold-layer').forEach((node) => node.remove());
  };

  const rleToSvgPath = (encoded) => {
    const cols = Number(encoded?.cols || 0);
    if (!cols || !Array.isArray(encoded?.runs)) return '';
    const commands = [];
    encoded.runs.forEach((run) => {
      let start = Number(run?.[0]);
      let remaining = Number(run?.[1]);
      while (Number.isFinite(start) && remaining > 0) {
        const x = start % cols;
        const y = Math.floor(start / cols);
        const width = Math.min(remaining, cols - x);
        commands.push(`M${x} ${y}h${width}v1h-${width}z`);
        start += width;
        remaining -= width;
      }
    });
    return commands.join('');
  };

  const renderFatThresholdOverlay = () => {
    removeFatThresholdOverlay();
    if (!fatThresholdState.fillVisible || !fatThresholdState.preview) return;
    const svg = getMainViewerCard()?.querySelector('.viewer-overlay');
    if (!svg) return;
    const candidatePath = rleToSvgPath(fatThresholdState.preview.masks?.candidate);
    const layer = createRulerSvgNode('g', {
      class: 'cvi-fat-threshold-layer',
      'pointer-events': 'none',
      'aria-label': '轮廓间脂肪区域预览'
    });
    if (candidatePath) {
      layer.appendChild(createRulerSvgNode('path', {
        class: 'cvi-fat-range-fill',
        d: candidatePath
      }));
    }
    const rulerLayer = svg.querySelector('.cvi-ruler-layer');
    if (rulerLayer) svg.insertBefore(layer, rulerLayer);
    else svg.appendChild(layer);
  };

  const lgeThresholdPreviewState = {
    identity: '',
    preview: null,
    loading: false,
    error: '',
    timer: null,
    requestToken: 0,
    scarVisible: true
  };

  const activeLgePreviewContext = () => {
    if (!isLgeProtocolActive()) return null;
    const activeKey = typeof window.__cviGetContourAutoSaveKey === 'function'
      ? String(window.__cviGetContourAutoSaveKey() || '')
      : '';
    const match = activeKey.match(/^lge:(\d+)$/);
    if (!match) return null;
    return {
      seriesId: Number(match[1]),
      sliceIndex: Number(getNavigatorInput('Slice')?.value || 0),
      phaseIndex: Number(getNavigatorInput('Phase')?.value || 0)
    };
  };

  const readLgeThresholdControls = (thresholdPanel) => {
    if (!(thresholdPanel instanceof HTMLElement)) return null;
    const method = Array.from(thresholdPanel.querySelectorAll('.tool-pill')).find((button) => (
      button.classList.contains('is-active')
    ))?.textContent?.trim().toLowerCase() || 'nsd';
    const sdField = Array.from(thresholdPanel.querySelectorAll('label')).find((label) => (
      label.querySelector('span')?.textContent?.trim() === 'n-SD 倍数'
    ));
    const greyZoneField = Array.from(thresholdPanel.querySelectorAll('label')).find((label) => (
      label.querySelector('span')?.textContent?.trim() === 'Grey Zone'
    ));
    return {
      method: method === 'fwhm' ? 'fwhm' : 'nsd',
      sdMultiplier: Number(sdField?.querySelector('input[type="range"]')?.value || 5),
      greyZone: Boolean(greyZoneField?.querySelector('input[type="checkbox"]')?.checked)
    };
  };

  const removeLgeThresholdOverlay = () => {
    document.querySelectorAll('.cvi-lge-threshold-layer').forEach((node) => node.remove());
  };

  const renderLgeThresholdOverlay = () => {
    removeLgeThresholdOverlay();
    if (!isLgeProtocolActive() || !lgeThresholdPreviewState.preview) return;
    const svg = getMainViewerCard()?.querySelector('.viewer-overlay');
    if (!svg) return;
    const scarPath = rleToSvgPath(lgeThresholdPreviewState.preview.masks?.scar);
    const greyZonePath = rleToSvgPath(lgeThresholdPreviewState.preview.masks?.grey_zone);
    const layer = createRulerSvgNode('g', {
      class: 'cvi-lge-threshold-layer',
      'pointer-events': 'none',
      'aria-label': 'LGE 阈值预览'
    });
    if (greyZonePath) {
      layer.appendChild(createRulerSvgNode('path', {
        class: 'cvi-lge-grey-zone-preview',
        d: greyZonePath
      }));
    }
    if (scarPath && lgeThresholdPreviewState.scarVisible) {
      layer.appendChild(createRulerSvgNode('path', {
        class: 'cvi-lge-scar-preview',
        d: scarPath
      }));
    }
    const firstContour = svg.querySelector('.contour');
    const contourRoot = firstContour
      ? Array.from(svg.children).find((child) => child === firstContour || child.contains(firstContour))
      : null;
    if (contourRoot) svg.insertBefore(layer, contourRoot);
    else svg.appendChild(layer);
  };

  const requestLgeThresholdPreview = async () => {
    const thresholdPanel = Array.from(document.querySelectorAll('.tool-group')).find((group) => (
      group.querySelector(':scope > strong')?.textContent?.trim() === 'LGE 阈值'
    ));
    const context = activeLgePreviewContext();
    const controls = readLgeThresholdControls(thresholdPanel);
    if (!context || !controls) {
      lgeThresholdPreviewState.preview = null;
      lgeThresholdPreviewState.error = '';
      removeLgeThresholdOverlay();
      return;
    }
    const identity = [
      context.seriesId,
      context.sliceIndex,
      context.phaseIndex,
      controls.method,
      controls.sdMultiplier,
      controls.greyZone ? 1 : 0
    ].join(':');
    lgeThresholdPreviewState.identity = identity;
    lgeThresholdPreviewState.loading = true;
    lgeThresholdPreviewState.error = '';
    const requestToken = ++lgeThresholdPreviewState.requestToken;
    scheduleApply();
    try {
      const response = await window.fetch(`${CVI_API_BASE}/measurements/lge-threshold-preview`, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({
          series_id: context.seriesId,
          slice_index: context.sliceIndex,
          phase_index: context.phaseIndex,
          threshold_method: controls.method,
          sd_multiplier: controls.sdMultiplier,
          grey_zone: controls.greyZone
        })
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || `HTTP ${response.status}`);
      }
      const preview = await response.json();
      if (requestToken !== lgeThresholdPreviewState.requestToken) return;
      lgeThresholdPreviewState.preview = preview;
      renderLgeThresholdOverlay();
    } catch (error) {
      if (requestToken !== lgeThresholdPreviewState.requestToken) return;
      lgeThresholdPreviewState.preview = null;
      lgeThresholdPreviewState.error = error instanceof Error ? error.message : String(error);
      removeLgeThresholdOverlay();
    } finally {
      if (requestToken === lgeThresholdPreviewState.requestToken) {
        lgeThresholdPreviewState.loading = false;
        scheduleApply();
      }
    }
  };

  const queueLgeThresholdPreview = () => {
    if (lgeThresholdPreviewState.timer) window.clearTimeout(lgeThresholdPreviewState.timer);
    lgeThresholdPreviewState.timer = window.setTimeout(() => {
      lgeThresholdPreviewState.timer = null;
      void requestLgeThresholdPreview();
    }, 180);
  };

  const requestFatThresholdPreview = async () => {
    let active = activeFatThresholdFrame();
    if (!active || !hasFatCandidateContours(active.frame, active.visibleContourKeys)
      || (!fatThresholdState.enabled && !fatThresholdState.fillVisible)) {
      fatThresholdState.preview = null;
      fatThresholdState.loading = false;
      removeFatThresholdOverlay();
      scheduleApply();
      return;
    }
    const requestIdentity = `${active.series.id}:${active.frameKey}`;
    fatThresholdState.loading = true;
    fatThresholdState.status = '正在计算预览...';
    scheduleApply();
    try {
      if (!hasFatCandidateContours(active.frame)) {
        if (typeof window.__cviFlushContourAutoSave === 'function') {
          await window.__cviFlushContourAutoSave('function', Number(active.series.id));
        }
        await refreshFunctionContourPayload(active.series.id);
        active = activeFatThresholdFrame();
        if (!active || !hasFatCandidateContours(active.frame)) {
          throw new Error('当前画面已有轮廓，但尚未保存到当前帧，请先保存轮廓');
        }
      }
      const response = await window.fetch(`${CVI_API_BASE}/measurements/fat-threshold-preview`, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({
          series_id: Number(active.series.id),
          slice_index: active.sliceIndex,
          phase_index: active.phaseIndex,
          lower: fatThresholdState.lower,
          upper: fatThresholdState.upper
        })
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || `HTTP ${response.status}`);
      }
      const preview = await response.json();
      if (fatThresholdState.identity !== requestIdentity) return;
      fatThresholdState.preview = preview;
      fatThresholdState.status = fatThresholdState.enabled
        ? '预览未保存'
        : fatThresholdState.fillVisible ? '脂肪区域显示已开启' : '';
      renderFatThresholdOverlay();
    } catch (error) {
      fatThresholdState.preview = null;
      fatThresholdState.status = `预览失败：${error instanceof Error ? error.message : String(error)}`;
      removeFatThresholdOverlay();
    } finally {
      fatThresholdState.loading = false;
      scheduleApply();
    }
  };

  const queueFatThresholdPreview = () => {
    if (fatThresholdState.timer) window.clearTimeout(fatThresholdState.timer);
    fatThresholdState.timer = window.setTimeout(() => {
      fatThresholdState.timer = null;
      void requestFatThresholdPreview();
    }, 180);
  };

  const saveFatThresholdForCurrentFrame = async (reset = false) => {
    const activeBeforeFlush = activeFatThresholdFrame();
    if (!activeBeforeFlush) return;
    fatThresholdState.saving = true;
    fatThresholdState.status = reset ? '正在恢复本帧...' : '正在保存本帧阈值...';
    scheduleApply();
    try {
      if (typeof window.__cviFlushContourAutoSave === 'function') {
        await window.__cviFlushContourAutoSave('function', Number(activeBeforeFlush.series.id));
      }
      await refreshFunctionContourPayload(activeBeforeFlush.series.id);
      const active = activeFatThresholdFrame();
      if (!active?.payload) throw new Error('请先保存当前轮廓');
      const nextPayload = JSON.parse(JSON.stringify(active.payload));
      nextPayload.settings = nextPayload.settings || {};
      const existing = nextPayload.settings.fat_threshold;
      const frames = { ...(existing?.frames || {}) };
      if (reset || !fatThresholdState.enabled) {
        delete frames[active.frameKey];
      } else {
        frames[active.frameKey] = {
          enabled: true,
          lower: Number(fatThresholdState.lower),
          upper: Number(fatThresholdState.upper)
        };
      }
      nextPayload.settings.fat_threshold = {
        enabled: Object.keys(frames).length > 0,
        frames
      };

      const response = await window.fetch(`${CVI_API_BASE}/contours/${Number(active.series.id)}?recompute=false`, {
        method: 'PUT',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify(nextPayload)
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || `HTTP ${response.status}`);
      }
      const saved = await response.json();
      window.__cviContourPayload = saved;
      window.__cviContourPayloadByKey = window.__cviContourPayloadByKey || {};
      window.__cviContourPayloadByKey[`${saved.series_id}:${saved.module}`] = saved;
      window.dispatchEvent(new CustomEvent('cvi:contours-updated', {
        detail: { seriesId: saved.series_id, module: saved.module }
      }));
      if (reset) {
        fatThresholdState.enabled = false;
        fatThresholdState.lower = 0;
        fatThresholdState.upper = 255;
        fatThresholdState.preview = null;
        fatThresholdState.drafts.delete(fatThresholdState.identity);
        fatThresholdState.dirty = false;
        fatThresholdState.status = '本帧已恢复为不筛选';
        removeFatThresholdOverlay();
      } else {
        fatThresholdState.drafts.delete(fatThresholdState.identity);
        fatThresholdState.dirty = false;
        fatThresholdState.status = '本帧阈值已保存；完成整套后再重算本序列指标';
        queueFatThresholdPreview();
      }
    } catch (error) {
      fatThresholdState.status = `保存失败：${error instanceof Error ? error.message : String(error)}`;
    } finally {
      fatThresholdState.saving = false;
      scheduleApply();
    }
  };

  const renderFatThresholdHistogram = (preview) => {
    const counts = preview?.histogram?.counts || [];
    const max = Math.max(1, ...counts);
    return counts.map((count, index) => (
      `<i style="height:${Math.max(2, Math.round((Number(count) / max) * 100))}%" data-bin="${index}"></i>`
    )).join('');
  };

  const ensureFatThresholdPanel = () => {
    const active = activeFatThresholdFrame();
    const host = getContourPanel();
    let fillPanel = document.querySelector('.cvi-fat-range-panel');
    let panel = document.querySelector('.cvi-fat-threshold-panel');
    if (!active || !host) {
      fillPanel?.remove();
      panel?.remove();
      removeFatThresholdOverlay();
      return;
    }

    const identity = `${active.series.id}:${active.frameKey}`;
    if (fatThresholdState.identity !== identity) {
      const config = active.payload?.settings?.fat_threshold;
      const frameConfig = config?.enabled ? config.frames?.[active.frameKey] : null;
      const draft = fatThresholdState.drafts.get(identity);
      if (Number(fatThresholdState.fillSeriesId) !== Number(active.series.id)) {
        fatThresholdState.fillSeriesId = Number(active.series.id);
        fatThresholdState.fillVisible = false;
      }
      fatThresholdState.identity = identity;
      fatThresholdState.enabled = draft
        ? Boolean(draft.enabled)
        : Boolean(frameConfig?.enabled !== false && frameConfig);
      fatThresholdState.lower = Number(draft?.lower ?? frameConfig?.lower ?? 0);
      fatThresholdState.upper = Number(draft?.upper ?? frameConfig?.upper ?? 255);
      fatThresholdState.preview = null;
      fatThresholdState.dragging = false;
      fatThresholdState.dirty = Boolean(draft);
      fatThresholdState.status = draft
        ? '已恢复本帧未保存阈值草稿'
        : fatThresholdState.enabled ? '正在恢复本帧预览...' : '';
      removeFatThresholdOverlay();
      if (fatThresholdState.enabled || fatThresholdState.fillVisible) queueFatThresholdPreview();
    }

    if (!fillPanel) {
      fillPanel = document.createElement('section');
      fillPanel.className = 'tool-group cvi-fat-range-panel';
      host.insertAdjacentElement('afterend', fillPanel);
    }
    if (!panel) {
      panel = document.createElement('section');
      panel.className = 'tool-group cvi-fat-threshold-panel';
      fillPanel.insertAdjacentElement('afterend', panel);
    }

    const hasCandidate = hasFatCandidateContours(active.frame, active.visibleContourKeys);
    const candidateStatus = fatCandidateContourStatus(active.frame, active.visibleContourKeys);
    const thresholdPreview = fatThresholdState.enabled ? fatThresholdState.preview : null;
    const stats = thresholdPreview?.stats;
    const fillHash = JSON.stringify({
      identity,
      hasCandidate,
      fillVisible: fatThresholdState.fillVisible,
      loading: fatThresholdState.loading,
      ventricularEpi: candidateStatus.ventricularEpi,
      epiFallback: candidateStatus.epiFallback,
      fatOuter: candidateStatus.fatOuter,
      legacyFat: candidateStatus.legacyFat
    });
    if (fillPanel.dataset.fatRangeHash !== fillHash) {
      fillPanel.dataset.fatRangeHash = fillHash;
      const fillHint = fatThresholdState.fillVisible
        ? hasCandidate
          ? '本序列显示已开启；切换到其他已勾画 slice / phase 时会自动显示。'
          : '本序列显示仍保持开启；当前帧没有完整脂肪候选区。'
        : '点一次后，本序列所有已勾画 slice / phase 在切换时都会自动显示。';
      fillPanel.innerHTML = [
        '<div class="cvi-fat-threshold-head"><strong>脂肪区域显示</strong><span>当前序列</span></div>',
        '<div class="cvi-fat-candidate-status">',
        `<span class="${candidateStatus.ventricularEpi || candidateStatus.epiFallback ? 'is-ready' : 'is-missing'}">心室外膜 ${candidateStatus.ventricularEpi ? '已标注' : candidateStatus.epiFallback ? '使用 epi' : '缺失'}</span>`,
        `<span class="${candidateStatus.fatOuter ? 'is-ready' : 'is-missing'}">脂肪壁层 ${candidateStatus.fatOuter ? '已标注' : '缺失'}</span>`,
        candidateStatus.legacyFat ? '<span class="is-ready">旧脂肪 ROI 可用</span>' : '',
        '</div>',
        `<button type="button" class="ghost-button ${fatThresholdState.fillVisible ? 'is-active' : ''}" data-fat-range-fill ${hasCandidate || fatThresholdState.fillVisible ? '' : 'disabled'} aria-pressed="${fatThresholdState.fillVisible ? 'true' : 'false'}">${fatThresholdState.fillVisible ? '隐藏脂肪区' : '显示脂肪区'}</button>`,
        `<p class="tool-hint">${fillHint}</p>`
      ].join('');
      fillPanel.querySelector('[data-fat-range-fill]')?.addEventListener('click', () => {
        fatThresholdState.fillVisible = !fatThresholdState.fillVisible;
        if (fatThresholdState.fillVisible) {
          fatThresholdState.status = '脂肪区域显示已开启';
          queueFatThresholdPreview();
        } else {
          removeFatThresholdOverlay();
          fatThresholdState.status = fatThresholdState.enabled
            ? '阈值计算仍保持启用；脂肪填色已关闭'
            : '脂肪填色已关闭';
        }
        scheduleApply();
      });
    }
    if (fatThresholdState.dragging) return;
    const hash = JSON.stringify({
      identity,
      hasCandidate,
      enabled: fatThresholdState.enabled,
      fillVisible: fatThresholdState.fillVisible,
      lower: fatThresholdState.lower,
      upper: fatThresholdState.upper,
      loading: fatThresholdState.loading,
      saving: fatThresholdState.saving,
      dirty: fatThresholdState.dirty,
      status: fatThresholdState.status,
      stats,
      histogram: thresholdPreview?.histogram?.counts
    });
    if (panel.dataset.fatThresholdHash === hash) {
      if (fatThresholdState.preview && fatThresholdState.fillVisible && !document.querySelector('.cvi-fat-threshold-layer')) {
        renderFatThresholdOverlay();
      }
      return;
    }
    panel.dataset.fatThresholdHash = hash;
    panel.innerHTML = [
      '<div class="cvi-fat-threshold-head"><strong>脂肪灰度筛选</strong><span>当前帧 · 0–255</span></div>',
      `<label class="checkbox-row"><input type="checkbox" data-fat-threshold-enable ${fatThresholdState.enabled ? 'checked' : ''} ${hasCandidate ? '' : 'disabled'}><span>启用当前帧筛选</span></label>`,
      hasCandidate ? '' : '<p class="tool-hint">当前帧没有完整脂肪候选区，灰度筛选保持禁用。</p>',
      `<div class="cvi-fat-threshold-histogram">${renderFatThresholdHistogram(thresholdPreview)}</div>`,
      `<label class="field compact"><span>灰度下限</span><input type="range" min="0" max="255" step="1" value="${fatThresholdState.lower}" data-fat-threshold-lower ${fatThresholdState.enabled ? '' : 'disabled'}><small data-fat-threshold-lower-value>${Math.round(fatThresholdState.lower)}</small></label>`,
      `<label class="field compact"><span>灰度上限</span><input type="range" min="0" max="255" step="1" value="${fatThresholdState.upper}" data-fat-threshold-upper ${fatThresholdState.enabled ? '' : 'disabled'}><small data-fat-threshold-upper-value>${Math.round(fatThresholdState.upper)}</small></label>`,
      stats ? [
        '<div class="cvi-fat-threshold-stats">',
        `<span>候选 <strong>${Number(stats.candidate?.area_mm2 || 0).toFixed(1)} mm²</strong></span>`,
        `<span>保留 <strong>${Number(stats.retained?.area_mm2 || 0).toFixed(1)} mm²</strong></span>`,
        `<span>阈值排除 <strong>${Number(stats.threshold_excluded?.area_mm2 || 0).toFixed(1)} mm²</strong></span>`,
        `<span>手工排除 <strong>${Number(stats.manual_excluded?.area_mm2 || 0).toFixed(1)} mm²</strong></span>`,
        '</div>'
      ].join('') : '',
      '<div class="inline-actions wrap">',
      `<button type="button" class="ghost-button" data-fat-threshold-apply ${hasCandidate && !fatThresholdState.saving ? '' : 'disabled'}>保存本帧阈值</button>`,
      `<button type="button" class="ghost-button" data-fat-threshold-reset ${fatThresholdState.saving ? 'disabled' : ''}>恢复本帧</button>`,
      '<button type="button" class="primary-button" data-fat-threshold-recompute>重算本序列指标</button>',
      '</div>',
      `<p class="status">${fatThresholdState.status || '拖动仅预览；保存本帧阈值后，完成整套再统一重算。'}</p>`
    ].join('');

    panel.querySelector('[data-fat-threshold-enable]')?.addEventListener('change', (event) => {
      fatThresholdState.enabled = Boolean(event.target.checked);
      rememberFatThresholdDraft();
      fatThresholdState.status = fatThresholdState.enabled
        ? '正在生成预览...'
        : fatThresholdState.fillVisible
          ? '正在保留脂肪区域填色...'
          : '筛选已在预览中关闭，点击应用后保存';
      if (fatThresholdState.enabled || fatThresholdState.fillVisible) queueFatThresholdPreview();
      else {
        fatThresholdState.preview = null;
        removeFatThresholdOverlay();
      }
      scheduleApply();
    });
    const lowerSlider = panel.querySelector('[data-fat-threshold-lower]');
    const upperSlider = panel.querySelector('[data-fat-threshold-upper]');
    const beginSliderDrag = () => {
      fatThresholdState.dragging = true;
    };
    const finishSliderDrag = () => {
      if (!fatThresholdState.dragging) return;
      fatThresholdState.dragging = false;
      queueFatThresholdPreview();
      scheduleApply();
    };
    [lowerSlider, upperSlider].forEach((slider) => {
      slider?.addEventListener('pointerdown', beginSliderDrag);
      slider?.addEventListener('pointerup', finishSliderDrag);
      slider?.addEventListener('pointercancel', finishSliderDrag);
      slider?.addEventListener('lostpointercapture', finishSliderDrag);
      slider?.addEventListener('change', finishSliderDrag);
    });
    lowerSlider?.addEventListener('input', (event) => {
      fatThresholdState.lower = Math.min(Number(event.target.value), fatThresholdState.upper);
      rememberFatThresholdDraft();
      panel.querySelector('[data-fat-threshold-lower-value]').textContent = String(Math.round(fatThresholdState.lower));
      queueFatThresholdPreview();
    });
    upperSlider?.addEventListener('input', (event) => {
      fatThresholdState.upper = Math.max(Number(event.target.value), fatThresholdState.lower);
      rememberFatThresholdDraft();
      panel.querySelector('[data-fat-threshold-upper-value]').textContent = String(Math.round(fatThresholdState.upper));
      queueFatThresholdPreview();
    });
    panel.querySelector('[data-fat-threshold-apply]')?.addEventListener('click', () => {
      void saveFatThresholdForCurrentFrame(false);
    });
    panel.querySelector('[data-fat-threshold-reset]')?.addEventListener('click', () => {
      void saveFatThresholdForCurrentFrame(true);
    });
    panel.querySelector('[data-fat-threshold-recompute]')?.addEventListener('click', () => {
      const sourceButton = findButtonByText(document, /^重算指标$/);
      if (!(sourceButton instanceof HTMLButtonElement) || sourceButton.disabled) return;
      fatThresholdState.status = '正在重算本序列指标...';
      sourceButton.click();
      scheduleApply();
    });
  };

  const ensureLgeThresholdPanelPlacement = () => {
    const inspectorHeading = document.querySelector('.inspector .panel-title h2');
    const inspectorModuleChip = inspectorHeading?.parentElement?.querySelector('.panel-chip');
    if (inspectorModuleChip && isLgeProtocolActive()) {
      inspectorModuleChip.textContent = 'lge';
    }
    const thresholdPanel = Array.from(document.querySelectorAll('.tool-group')).find((group) => {
      return group.querySelector(':scope > strong')?.textContent?.trim() === 'LGE 阈值';
    });
    if (!isLgeProtocolActive()) {
      thresholdPanel?.classList.remove('cvi-lge-threshold-priority');
      lgeThresholdPreviewState.preview = null;
      lgeThresholdPreviewState.error = '';
      removeLgeThresholdOverlay();
      return;
    }
    if (!thresholdPanel) return;
    thresholdPanel.classList.add('cvi-lge-threshold-priority');
    const contourPanel = getContourPanel();
    if (contourPanel?.parentElement && thresholdPanel.previousElementSibling !== contourPanel) {
      contourPanel.insertAdjacentElement('afterend', thresholdPanel);
    }

    const methodButtons = Array.from(thresholdPanel.querySelectorAll('.tool-pill'));
    const activeMethod = methodButtons.find((button) => button.classList.contains('is-active'))
      ?.textContent?.trim().toLowerCase() || 'nsd';
    const sdField = Array.from(thresholdPanel.querySelectorAll('label')).find((label) => (
      label.querySelector('span')?.textContent?.trim() === 'n-SD 倍数'
    ));
    const sdInput = sdField?.querySelector('input[type="range"]');
    const sdValue = sdField?.querySelector('small');
    if (sdInput instanceof HTMLInputElement) {
      sdInput.disabled = activeMethod === 'fwhm';
    }
    if (sdValue instanceof HTMLElement) {
      const nextValue = activeMethod === 'fwhm'
        ? 'FWHM 模式不使用 n-SD'
        : `${Number(sdInput?.value || 0).toFixed(1)} SD`;
      if (sdValue.textContent !== nextValue) sdValue.textContent = nextValue;
    }

    methodButtons.forEach((button) => {
      if (button.dataset.cviLgePreviewBound === '1') return;
      button.dataset.cviLgePreviewBound = '1';
      button.addEventListener('click', () => window.setTimeout(queueLgeThresholdPreview, 0));
    });
    if (sdInput instanceof HTMLInputElement && sdInput.dataset.cviLgePreviewBound !== '1') {
      sdInput.dataset.cviLgePreviewBound = '1';
      sdInput.addEventListener('input', queueLgeThresholdPreview);
      sdInput.addEventListener('change', queueLgeThresholdPreview);
    }
    const greyZoneInput = Array.from(thresholdPanel.querySelectorAll('label')).find((label) => (
      label.querySelector('span')?.textContent?.trim() === 'Grey Zone'
    ))?.querySelector('input[type="checkbox"]');
    if (greyZoneInput instanceof HTMLInputElement && greyZoneInput.dataset.cviLgePreviewBound !== '1') {
      greyZoneInput.dataset.cviLgePreviewBound = '1';
      greyZoneInput.addEventListener('change', () => window.setTimeout(queueLgeThresholdPreview, 0));
    }

    const previewContext = activeLgePreviewContext();
    const previewControls = readLgeThresholdControls(thresholdPanel);
    const previewIdentity = previewContext && previewControls ? [
      previewContext.seriesId,
      previewContext.sliceIndex,
      previewContext.phaseIndex,
      previewControls.method,
      previewControls.sdMultiplier,
      previewControls.greyZone ? 1 : 0
    ].join(':') : '';
    if (previewIdentity && previewIdentity !== lgeThresholdPreviewState.identity && !lgeThresholdPreviewState.loading) {
      lgeThresholdPreviewState.preview = null;
      removeLgeThresholdOverlay();
      queueLgeThresholdPreview();
    } else if (lgeThresholdPreviewState.preview && !document.querySelector('.cvi-lge-threshold-layer')) {
      renderLgeThresholdOverlay();
    }

    let resultRow = thresholdPanel.querySelector('.cvi-lge-grey-zone-result');
    if (!(resultRow instanceof HTMLElement)) {
      resultRow = document.createElement('div');
      resultRow.className = 'metric-row cvi-lge-grey-zone-result';
      resultRow.innerHTML = '<span>全序列 Grey Zone（上次重算）</span><strong>—</strong>';
      thresholdPanel.appendChild(resultRow);
    }
    const greyZoneMetric = Array.from(document.querySelectorAll('.metric-table-row')).find((row) => (
      row.querySelector('span')?.textContent?.trim() === 'Grey Zone'
    ));
    const greyZoneValue = greyZoneMetric?.querySelector('strong')?.textContent?.trim() || '—';
    const resultValue = resultRow.querySelector('strong');
    if (resultValue && resultValue.textContent !== greyZoneValue) resultValue.textContent = greyZoneValue;

    let previewRow = thresholdPanel.querySelector('.cvi-lge-preview-result');
    if (!(previewRow instanceof HTMLElement)) {
      previewRow = document.createElement('div');
      previewRow.className = 'cvi-lge-preview-result';
      previewRow.innerHTML = [
        '<div class="cvi-lge-preview-legend">',
        '<label class="checkbox-row compact"><input type="checkbox" data-cvi-lge-scar-visible checked><span><i class="is-scar"></i>显示 Scar</span></label>',
        '<span><i class="is-grey-zone"></i>Grey Zone</span>',
        '</div>',
        '<strong>当前层预览：—</strong>'
      ].join('');
      thresholdPanel.appendChild(previewRow);
    }
    const scarVisibilityInput = previewRow.querySelector('[data-cvi-lge-scar-visible]');
    if (scarVisibilityInput instanceof HTMLInputElement) {
      scarVisibilityInput.checked = lgeThresholdPreviewState.scarVisible;
      if (scarVisibilityInput.dataset.cviLgeScarVisibilityBound !== '1') {
        scarVisibilityInput.dataset.cviLgeScarVisibilityBound = '1';
        scarVisibilityInput.addEventListener('change', () => {
          lgeThresholdPreviewState.scarVisible = scarVisibilityInput.checked;
          renderLgeThresholdOverlay();
          scheduleApply();
        });
      }
    }
    const previewStats = lgeThresholdPreviewState.preview?.stats;
    const previewCopy = lgeThresholdPreviewState.loading
      ? '当前层预览：正在生成...'
      : lgeThresholdPreviewState.error
        ? `当前层预览失败：${lgeThresholdPreviewState.error}`
        : previewStats
          ? lgeThresholdPreviewState.scarVisible
            ? `当前层 P${Number(lgeThresholdPreviewState.preview?.phase_index || 0) + 1} 预览：Scar ${Number(previewStats.scar?.area_mm2 || 0).toFixed(1)} mm² / Grey ${Number(previewStats.grey_zone?.area_mm2 || 0).toFixed(1)} mm²`
            : `当前层 P${Number(lgeThresholdPreviewState.preview?.phase_index || 0) + 1} 预览：Grey ${Number(previewStats.grey_zone?.area_mm2 || 0).toFixed(1)} mm²`
          : '当前层预览：—';
    const previewValue = previewRow.querySelector(':scope > strong');
    if (previewValue && previewValue.textContent !== previewCopy) previewValue.textContent = previewCopy;

    let actionRow = thresholdPanel.querySelector('.cvi-lge-threshold-actions');
    if (!(actionRow instanceof HTMLElement)) {
      actionRow = document.createElement('div');
      actionRow.className = 'inline-actions wrap cvi-lge-threshold-actions';
      const applyButton = document.createElement('button');
      applyButton.type = 'button';
      applyButton.className = 'primary-button';
      applyButton.dataset.cviLgeThresholdApply = '1';
      applyButton.textContent = '应用阈值并重算';
      applyButton.addEventListener('click', () => {
        const sourceButton = Array.from(document.querySelectorAll('button')).find((button) => (
          button !== applyButton && button.textContent?.trim() === '重算指标'
        ));
        if (!(sourceButton instanceof HTMLButtonElement) || sourceButton.disabled) return;
        sourceButton.click();
        applyButton.disabled = true;
        applyButton.textContent = '正在重算...';
        window.setTimeout(scheduleApply, 250);
      });
      actionRow.appendChild(applyButton);
      thresholdPanel.appendChild(actionRow);
    }
    const sourceRecomputeButton = Array.from(document.querySelectorAll('button')).find((button) => (
      button.textContent?.trim() === '重算指标'
    ));
    const applyButton = actionRow.querySelector('[data-cvi-lge-threshold-apply="1"]');
    if (applyButton instanceof HTMLButtonElement) {
      const sourceBusy = !(sourceRecomputeButton instanceof HTMLButtonElement) || sourceRecomputeButton.disabled;
      applyButton.disabled = sourceBusy;
      const nextLabel = sourceBusy ? '正在重算...' : '应用阈值并重算';
      if (applyButton.textContent !== nextLabel) applyButton.textContent = nextLabel;
    }
  };

  const runTrackingPreview = async (seriesId) => {
    if (!Number.isFinite(Number(seriesId)) || window.__cviTrackingPreviewRunning) return;
    window.__cviTrackingPreviewRunning = true;
    window.__cviTrackingPreviewError = '';
    let timeoutId = null;
    scheduleApply();
    try {
      if (typeof window.__cviFlushContourAutoSave === 'function') {
        await window.__cviFlushContourAutoSave('function', Number(seriesId));
      } else if (typeof window.__cviFlushContourAutoSaveByKey === 'function') {
        await window.__cviFlushContourAutoSaveByKey(`function:${Number(seriesId)}`);
      }
      const controller = new AbortController();
      timeoutId = window.setTimeout(() => controller.abort(), 60000);
      const response = await window.fetch(`${CVI_API_BASE}/measurements/tracking-preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ series_id: Number(seriesId) }),
        signal: controller.signal
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || '追踪验证失败。');
      captureMeasurementPayload(payload);
    } catch (error) {
      window.__cviTrackingPreviewError = error?.name === 'AbortError'
        ? '追踪验证超过 60 秒，已停止等待；请减少人工相邻帧后重试。'
        : (error instanceof Error ? error.message : '追踪验证失败。');
    } finally {
      if (timeoutId != null) window.clearTimeout(timeoutId);
      window.__cviTrackingPreviewRunning = false;
      scheduleApply();
    }
  };

  const strainChart = (strain) => {
    const curve = Array.isArray(strain?.curve) ? strain.curve : [];
    const role = String(strain?.role || '');
    const definitions = role.startsWith('cine_lax_')
      ? [{ key: 'gls_proxy_percent', label: 'GLS proxy', color: '#ff7c82' }]
      : [
          { key: 'gcs_proxy_percent', label: 'GCS proxy', color: '#57e389' },
          { key: 'grs_proxy_percent', label: 'GRS proxy', color: '#65d6ff' }
        ];
    const seriesValues = definitions.map((definition) => ({
      ...definition,
      values: curve.map((item) => ({
        phase: Number(item?.phase_index),
        value: Number(item?.[definition.key])
      })).filter((item) => Number.isFinite(item.phase) && Number.isFinite(item.value))
    }));
    const allPoints = seriesValues.flatMap((item) => item.values);
    if (new Set(allPoints.map((item) => item.phase)).size < 2) {
      return '<div class="empty-state">至少保存两个含所需心内膜/心外膜轮廓的相位后，才会生成应变 proxy 曲线。</div>';
    }

    const width = 300;
    const height = 142;
    const left = 34;
    const right = 12;
    const top = 14;
    const bottom = 28;
    const phases = allPoints.map((item) => item.phase);
    const values = allPoints.map((item) => item.value);
    const phaseMin = Math.min(...phases);
    const phaseMax = Math.max(...phases);
    const valueMin = Math.min(0, ...values);
    const valueMax = Math.max(0, ...values);
    const phaseSpan = Math.max(1, phaseMax - phaseMin);
    const valueSpan = Math.max(1, valueMax - valueMin);
    const xAt = (phase) => left + ((phase - phaseMin) / phaseSpan) * (width - left - right);
    const yAt = (value) => top + ((valueMax - value) / valueSpan) * (height - top - bottom);
    const zeroY = yAt(0);
    const polylines = seriesValues.map((item) => {
      const points = item.values.map((point) => `${xAt(point.phase).toFixed(1)},${yAt(point.value).toFixed(1)}`).join(' ');
      const circles = item.values.map((point) => (
        `<circle cx="${xAt(point.phase).toFixed(1)}" cy="${yAt(point.value).toFixed(1)}" r="2.4" fill="${item.color}"/>`
      )).join('');
      return `<polyline fill="none" stroke="${item.color}" stroke-width="2" points="${points}"/>${circles}`;
    }).join('');
    const marker = (phase, label, color) => {
      const numeric = Number(phase);
      if (!Number.isFinite(numeric) || numeric < phaseMin || numeric > phaseMax) return '';
      const x = xAt(numeric).toFixed(1);
      return `<g><line x1="${x}" y1="${top}" x2="${x}" y2="${height - bottom}" stroke="${color}" stroke-width="1" stroke-dasharray="4 3"/><text x="${x}" y="${height - 9}" fill="${color}" text-anchor="middle">${label} ${numeric}</text></g>`;
    };
    const legend = seriesValues.map((item) => (
      `<span><i style="background:${item.color}"></i>${item.label}</span>`
    )).join('');
    return [
      '<article class="cvi-strain-chart">',
      `<div class="cvi-strain-legend">${legend}</div>`,
      `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="2D 应变 proxy 随相位变化曲线">`,
      `<line x1="${left}" y1="${zeroY.toFixed(1)}" x2="${width - right}" y2="${zeroY.toFixed(1)}" stroke="rgba(255,255,255,.24)" stroke-width="1"/>`,
      `<text x="4" y="${Math.max(12, zeroY - 4).toFixed(1)}" fill="#b0b0b0">0%</text>`,
      polylines,
      marker(strain?.ed_phase, 'ED', '#d8f271'),
      marker(strain?.es_phase, 'ES', '#ff9f43'),
      '</svg>',
      '</article>'
    ].join('');
  };

  const leftAtrialVolumeChart = (atrial) => {
    const curve = (Array.isArray(atrial?.curve) ? atrial.curve : [])
      .map((item) => ({
        phase: Number(item?.phase_index),
        volume: Number(item?.volume_proxy_ml)
      }))
      .filter((item) => Number.isFinite(item.phase) && Number.isFinite(item.volume));
    if (curve.length < 2) {
      return '<div class="empty-state">至少保存两个相位的左房轮廓并重算指标后，才会生成左房容积曲线。</div>';
    }

    const width = 300;
    const height = 142;
    const left = 38;
    const right = 12;
    const top = 14;
    const bottom = 28;
    const phases = curve.map((item) => item.phase);
    const volumes = curve.map((item) => item.volume);
    const phaseMin = Math.min(...phases);
    const phaseMax = Math.max(...phases);
    const volumeMin = Math.min(...volumes);
    const volumeMax = Math.max(...volumes);
    const phaseSpan = Math.max(1, phaseMax - phaseMin);
    const volumePadding = Math.max(0.1, (volumeMax - volumeMin) * 0.12);
    const axisMin = Math.max(0, volumeMin - volumePadding);
    const axisMax = Math.max(axisMin + 0.1, volumeMax + volumePadding);
    const volumeSpan = axisMax - axisMin;
    const xAt = (phase) => left + ((phase - phaseMin) / phaseSpan) * (width - left - right);
    const yAt = (volume) => top + ((axisMax - volume) / volumeSpan) * (height - top - bottom);
    const points = curve.map((item) => `${xAt(item.phase).toFixed(1)},${yAt(item.volume).toFixed(1)}`).join(' ');
    const circles = curve.map((item) => (
      `<circle cx="${xAt(item.phase).toFixed(1)}" cy="${yAt(item.volume).toFixed(1)}" r="2.5" fill="#65d6ff"/>`
    )).join('');
    const phaseSelection = atrial?.phase_selection || {};
    const marker = (phase, label, color) => {
      const numeric = Number(phase);
      if (!Number.isFinite(numeric) || numeric < phaseMin || numeric > phaseMax) return '';
      const x = xAt(numeric).toFixed(1);
      return `<g><line x1="${x}" y1="${top}" x2="${x}" y2="${height - bottom}" stroke="${color}" stroke-width="1" stroke-dasharray="4 3"/><text x="${x}" y="${height - 9}" fill="${color}" text-anchor="middle">${label} ${numeric}</text></g>`;
    };
    return [
      '<article class="cvi-strain-chart cvi-la-volume-chart">',
      '<div class="cvi-strain-legend"><span><i style="background:#65d6ff"></i>左房容积估算</span></div>',
      `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="左房单平面容积随相位变化曲线">`,
      `<line x1="${left}" y1="${height - bottom}" x2="${width - right}" y2="${height - bottom}" stroke="rgba(255,255,255,.24)" stroke-width="1"/>`,
      `<text x="4" y="${top + 4}" fill="#b0b0b0">${formatTrackingValue(axisMax, 1)}</text>`,
      `<text x="4" y="${height - bottom}" fill="#b0b0b0">${formatTrackingValue(axisMin, 1)}</text>`,
      `<polyline fill="none" stroke="#65d6ff" stroke-width="2" points="${points}"/>`,
      circles,
      marker(phaseSelection.la_max, 'max', '#d8f271'),
      marker(phaseSelection.la_pre_a, 'pre-A', '#ffcf5a'),
      marker(phaseSelection.la_min, 'min', '#ff8c94'),
      '</svg>',
      '</article>'
    ].join('');
  };

  const leftAtrialStrainChart = (strain) => {
    const curve = (Array.isArray(strain?.curve) ? strain.curve : [])
      .map((item) => ({ phase: Number(item?.phase_index), value: Number(item?.longitudinal_strain_proxy_percent) }))
      .filter((item) => Number.isFinite(item.phase) && Number.isFinite(item.value));
    if (curve.length < 2) return '';
    const width = 300;
    const height = 128;
    const left = 34;
    const right = 12;
    const top = 12;
    const bottom = 25;
    const phaseMin = Math.min(...curve.map((item) => item.phase));
    const phaseMax = Math.max(...curve.map((item) => item.phase));
    const valueMin = Math.min(0, ...curve.map((item) => item.value));
    const valueMax = Math.max(1, ...curve.map((item) => item.value));
    const xAt = (phase) => left + ((phase - phaseMin) / Math.max(1, phaseMax - phaseMin)) * (width - left - right);
    const yAt = (value) => top + ((valueMax - value) / Math.max(1, valueMax - valueMin)) * (height - top - bottom);
    const points = curve.map((item) => `${xAt(item.phase).toFixed(1)},${yAt(item.value).toFixed(1)}`).join(' ');
    const circles = curve.map((item) => `<circle cx="${xAt(item.phase).toFixed(1)}" cy="${yAt(item.value).toFixed(1)}" r="2.4" fill="#ff8c94"/>`).join('');
    return [
      '<article class="cvi-strain-chart cvi-la-strain-chart">',
      '<div class="cvi-strain-legend"><span><i style="background:#ff8c94"></i>左房纵向应变 proxy</span></div>',
      `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="左房轮廓应变随相位变化曲线">`,
      `<line x1="${left}" y1="${yAt(0).toFixed(1)}" x2="${width - right}" y2="${yAt(0).toFixed(1)}" stroke="rgba(255,255,255,.24)" stroke-width="1"/>`,
      `<polyline fill="none" stroke="#ff8c94" stroke-width="2" points="${points}"/>`,
      circles,
      '</svg>',
      '</article>'
    ].join('');
  };

  const leftAtrialSettingsState = {
    seriesId: null,
    saving: false,
    status: ''
  };

  const saveLeftAtrialBsa = async (seriesId, rawValue, reset = false) => {
    const numeric = Number(rawValue);
    if (!reset && (!Number.isFinite(numeric) || numeric < 0.5 || numeric > 3.5)) {
      leftAtrialSettingsState.status = 'BSA 请输入 0.50–3.50 m²';
      scheduleApply();
      return;
    }
    leftAtrialSettingsState.seriesId = Number(seriesId);
    leftAtrialSettingsState.saving = true;
    leftAtrialSettingsState.status = reset ? '正在清除 BSA...' : '正在保存 BSA...';
    scheduleApply();
    try {
      if (typeof window.__cviFlushContourAutoSave === 'function') {
        await window.__cviFlushContourAutoSave('function', Number(seriesId));
      }
      const current = await refreshFunctionContourPayload(Number(seriesId));
      const nextPayload = JSON.parse(JSON.stringify(current));
      nextPayload.settings = nextPayload.settings || {};
      const config = { ...(nextPayload.settings.left_atrial_function || {}) };
      if (reset) delete config.bsa_m2;
      else config.bsa_m2 = numeric;
      nextPayload.settings.left_atrial_function = config;
      const saveResponse = await window.fetch(`${CVI_API_BASE}/contours/${Number(seriesId)}`, {
        method: 'PUT',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify(nextPayload)
      });
      const saved = await saveResponse.json().catch(() => ({}));
      if (!saveResponse.ok) throw new Error(saved.detail || `HTTP ${saveResponse.status}`);
      window.__cviContourPayload = saved;
      window.__cviContourPayloadByKey = window.__cviContourPayloadByKey || {};
      window.__cviContourPayloadByKey[`${saved.series_id}:${saved.module}`] = saved;
      const measurementResponse = await window.fetch(`${CVI_API_BASE}/measurements/function`, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ series_id: Number(seriesId) })
      });
      const measurement = await measurementResponse.json().catch(() => ({}));
      if (!measurementResponse.ok) throw new Error(measurement.detail || `HTTP ${measurementResponse.status}`);
      captureMeasurementPayload(measurement);
      leftAtrialSettingsState.status = reset ? 'BSA 已清除' : 'BSA 与 LAVi 已重算';
    } catch (error) {
      leftAtrialSettingsState.status = `保存失败：${error instanceof Error ? error.message : String(error)}`;
    } finally {
      leftAtrialSettingsState.saving = false;
      scheduleApply();
    }
  };

  const ensureLeftAtrialFunctionPanel = () => {
    const inspector = document.querySelector('.inspector');
    if (!(inspector instanceof HTMLElement)) return;
    const series = activeFunctionSeries();
    let panel = inspector.querySelector('.cvi-left-atrial-panel');
    if (!series || String(series.role || '') !== 'cine_lax_4ch') {
      panel?.remove();
      return;
    }

    const payload = window.__cviMeasurementPayloadBySeries?.[String(series.id)]
      || (series.latest_measurement?.research?.left_atrial_function ? series.latest_measurement : null);
    const atrial = payload?.research?.left_atrial_function || null;
    if (leftAtrialSettingsState.seriesId !== Number(series.id) && !leftAtrialSettingsState.saving) {
      leftAtrialSettingsState.seriesId = Number(series.id);
      leftAtrialSettingsState.status = '';
    }
    if (!panel) {
      panel = document.createElement('section');
      panel.className = 'panel-section research-panel cvi-left-atrial-panel';
      const anchor = inspector.querySelector('.research-panel') || inspector.querySelector('.metric-table-shell');
      if (anchor?.parentElement) {
        anchor.parentElement.insertBefore(panel, anchor.nextSibling);
      } else {
        inspector.appendChild(panel);
      }
    }

    const contourBsa = activeFunctionContourPayload(series)?.settings?.left_atrial_function?.bsa_m2;
    const effectiveBsa = Number.isFinite(Number(contourBsa)) ? Number(contourBsa) : Number(atrial?.indexing?.bsa_m2);
    const hash = JSON.stringify({
      series_id: series.id,
      atrial,
      effectiveBsa: Number.isFinite(effectiveBsa) ? effectiveBsa : null,
      settingsSaving: leftAtrialSettingsState.saving,
      settingsStatus: leftAtrialSettingsState.status
    });
    if (panel.dataset.leftAtrialHash === hash) return;
    panel.dataset.leftAtrialHash = hash;

    const summary = atrial?.summary || {};
    const biplane = atrial?.biplane || {};
    const biplaneSummary = biplane?.summary || {};
    const atrialStrain = atrial?.strain_proxy || {};
    const atrialStrainSummary = atrialStrain?.summary || {};
    const phases = atrial?.phase_selection || {};
    const quality = atrial?.quality || {};
    const curveByPhase = new Map(
      (Array.isArray(atrial?.curve) ? atrial.curve : []).map((item) => [Number(item?.phase_index), item])
    );
    const volumeCard = (label, value, phase) => {
      const source = curveByPhase.get(Number(phase));
      const sourceAttrs = source
        ? ` data-la-slice="${Number(source.slice_index)}" data-la-phase="${Number(source.phase_index)}" title="跳转到该关键相位"`
        : '';
      return `<button type="button" class="research-summary-card cvi-la-phase-card"${sourceAttrs}><span>${label}</span><strong>${formatTrackingValue(value, 2)} mL</strong><small>Phase ${formatTrackingValue(phase, 0)}</small></button>`;
    };
    const fractionCard = (label, value) => (
      `<div class="research-summary-card"><span>${label}</span><strong>${formatTrackingValue(value, 2)}%</strong></div>`
    );
    const metricCard = (label, value, unit) => (
      `<div class="research-summary-card"><span>${label}</span><strong>${formatTrackingValue(value, 2)}${unit ? ` ${unit}` : ''}</strong></div>`
    );
    const statusLabels = {
      unavailable: '暂无左房轮廓',
      partial: '关键相位不足',
      max_min_complete: 'max / min 已齐',
      key_phases_complete: '三关键相位已齐',
      invalid_volume_order: '关键相位或轮廓顺序异常'
    };
    const statusLabel = statusLabels[String(quality.status || '')] || '等待重算';
    const phaseCards = atrial ? [
      volumeCard('LAVmax', summary.lav_max_ml, phases.la_max),
      volumeCard('LAVpre-A', summary.lav_pre_a_ml, phases.la_pre_a),
      volumeCard('LAVmin', summary.lav_min_ml, phases.la_min)
    ].join('') : '';
    const functionCards = atrial ? [
      fractionCard('总排空分数', summary.total_emptying_fraction_percent),
      fractionCard('被动排空分数', summary.passive_emptying_fraction_percent),
      fractionCard('主动排空分数', summary.active_emptying_fraction_percent)
    ].join('') : '';
    const strainCards = atrial ? [
      fractionCard('Reservoir strain', atrialStrainSummary.reservoir_strain_proxy_percent),
      fractionCard('Conduit strain', atrialStrainSummary.conduit_strain_proxy_percent),
      fractionCard('Contractile strain', atrialStrainSummary.contractile_strain_proxy_percent)
    ].join('') : '';
    const biplaneCards = biplaneSummary.lav_max_ml != null ? [
      metricCard('双平面 LAVmax', biplaneSummary.lav_max_ml, 'mL'),
      metricCard('双平面 LAVpre-A', biplaneSummary.lav_pre_a_ml, 'mL'),
      metricCard('双平面 LAVmin', biplaneSummary.lav_min_ml, 'mL')
    ].join('') : '';
    const laviCards = biplaneSummary.lavi_max_ml_m2 != null ? [
      metricCard('LAVi max', biplaneSummary.lavi_max_ml_m2, 'mL/m²'),
      metricCard('LAVi pre-A', biplaneSummary.lavi_pre_a_ml_m2, 'mL/m²'),
      metricCard('LAVi min', biplaneSummary.lavi_min_ml_m2, 'mL/m²')
    ].join('') : '';
    const biplaneStatusLabels = {
      missing_2ch: '2CH 轮廓未就绪',
      partial: '双平面关键相位不足',
      max_min_complete: '双平面 max / min 已齐',
      key_phases_complete: '双平面三关键相位已齐',
      invalid_volume_order: '双平面相位或轮廓顺序异常'
    };
    const biplaneStatus = biplaneStatusLabels[String(biplane?.status || '')] || '等待 2CH 数据';
    const bsaValue = Number.isFinite(effectiveBsa) ? effectiveBsa.toFixed(2) : '';

    panel.innerHTML = [
      '<div class="research-panel-head"><strong>左房功能</strong><span>4CH 单平面 / 2CH+4CH 双平面</span></div>',
      atrial
        ? `<div class="cvi-la-quality"><span>${statusLabel}</span><strong>${formatTrackingValue(quality.annotated_phase_count, 0)} / ${formatTrackingValue(quality.total_phase_count, 0)} 相</strong></div>`
        : '',
      phaseCards ? `<div class="research-summary cvi-la-summary">${phaseCards}</div>` : '',
      functionCards ? `<div class="research-summary cvi-la-summary">${functionCards}</div>` : '',
      atrial ? leftAtrialVolumeChart(atrial) : '<div class="empty-state">保存 4CH 左房轮廓并点击“重算指标”后，此处显示左房容积和排空功能。</div>',
      atrial ? '<div class="cvi-la-section-title"><strong>左房应变</strong><span>LA min 零参考</span></div>' : '',
      strainCards ? `<div class="research-summary cvi-la-summary">${strainCards}</div>` : '',
      atrial ? leftAtrialStrainChart(atrialStrain) : '',
      atrial ? `<div class="cvi-la-section-title"><strong>双平面容积</strong><span>${biplaneStatus}</span></div>` : '',
      biplaneCards ? `<div class="research-summary cvi-la-summary">${biplaneCards}</div>` : '',
      `<div class="cvi-la-bsa-row"><label><span>BSA</span><input type="number" min="0.5" max="3.5" step="0.01" value="${bsaValue}" data-cvi-la-bsa-input="1"><small>m²</small></label><button type="button" class="ghost-button" data-cvi-la-bsa-save="1" ${leftAtrialSettingsState.saving ? 'disabled' : ''}>${leftAtrialSettingsState.saving ? '保存中...' : '保存 BSA'}</button><button type="button" class="ghost-button" data-cvi-la-bsa-clear="1" ${leftAtrialSettingsState.saving || !bsaValue ? 'disabled' : ''} title="清除 BSA">清除</button></div>`,
      leftAtrialSettingsState.status ? `<div class="status">${escapeHtml(leftAtrialSettingsState.status)}</div>` : '',
      laviCards ? `<div class="research-summary cvi-la-summary">${laviCards}</div>` : ''
    ].join('');

    panel.querySelectorAll('[data-la-slice][data-la-phase]').forEach((button) => {
      button.addEventListener('click', () => {
        jumpToResearchSource([{
          slice_index: Number(button.getAttribute('data-la-slice')),
          phase_index: Number(button.getAttribute('data-la-phase'))
        }]);
      });
    });
    panel.querySelector('[data-cvi-la-bsa-save="1"]')?.addEventListener('click', () => {
      const input = panel.querySelector('[data-cvi-la-bsa-input="1"]');
      void saveLeftAtrialBsa(Number(series.id), input?.value || '', false);
    });
    panel.querySelector('[data-cvi-la-bsa-clear="1"]')?.addEventListener('click', () => {
      void saveLeftAtrialBsa(Number(series.id), '', true);
    });
  };

  const ensureTrackingValidationPanel = () => {
    const inspector = document.querySelector('.inspector');
    if (!(inspector instanceof HTMLElement)) return;
    const series = activeFunctionSeries();
    let panel = inspector.querySelector('.cvi-tracking-panel');
    if (!series) {
      panel?.remove();
      return;
    }

    const payload = window.__cviMeasurementPayloadBySeries?.[String(series.id)]
      || (series.latest_measurement?.research?.tracking_validation ? series.latest_measurement : null);
    const trackingCandidate = payload?.research?.tracking_validation || null;
    const tracking = payload?.module === 'tracking_preview' && trackingCandidate?.status === 'completed'
      ? trackingCandidate
      : null;
    const strain = payload?.research?.strain_proxy || null;
    const running = Boolean(window.__cviTrackingPreviewRunning);
    const error = String(window.__cviTrackingPreviewError || '');

    if (!panel) {
      panel = document.createElement('section');
      panel.className = 'panel-section research-panel cvi-tracking-panel';
      const anchor = inspector.querySelector('.research-panel') || inspector.querySelector('.metric-table-shell');
      if (anchor?.parentElement) {
        anchor.parentElement.insertBefore(panel, anchor.nextSibling);
      } else {
        inspector.appendChild(panel);
      }
    }

    const hash = JSON.stringify({
      series_id: series.id,
      running,
      error,
      tracking,
      strain
    });
    if (panel.dataset.trackingHash === hash) return;
    panel.dataset.trackingHash = hash;

    const summary = tracking?.summary || {};
    const strainSummary = strain?.summary || {};
    const strainCards = [
      ['GLS proxy', strainSummary.gls_peak_percent],
      ['GCS proxy', strainSummary.gcs_peak_percent],
      ['GRS proxy', strainSummary.grs_peak_percent]
    ].filter(([, value]) => Number.isFinite(Number(value))).map(([label, value]) => (
      `<div class="research-summary-card"><span>${label}</span><strong>${formatTrackingValue(value, 2)}%</strong></div>`
    )).join('');
    const strainQualityCards = strain ? [
      `<div class="research-summary-card"><span>ED / ES</span><strong>${formatTrackingValue(strain.ed_phase, 0)} / ${formatTrackingValue(strain.es_phase, 0)}</strong></div>`,
      `<div class="research-summary-card"><span>可用相位</span><strong>${formatTrackingValue(strain.quality?.usable_phase_count, 0)} / ${formatTrackingValue(strain.quality?.total_phase_count, 0)}</strong></div>`
    ].join('') : '';
    const regionCards = ['endo', 'epi', 'myocardium', 'la'].map((regionKey) => {
      const item = summary[regionKey] || {};
      if (!item.pair_count) return '';
      return [
        '<article class="research-card cvi-tracking-card">',
        `<div class="research-card-head"><strong>${trackingRegionLabel(regionKey)}</strong><span>${item.pair_count} 对</span></div>`,
        '<div class="research-metric-list">',
        `<div class="research-metric-row"><span>平均 Dice</span><strong>${formatTrackingValue(item.mean_dice, 3)}</strong></div>`,
        `<div class="research-metric-row"><span>最低 Dice</span><strong>${formatTrackingValue(item.min_dice, 3)}</strong></div>`,
        `<div class="research-metric-row"><span>边界误差</span><strong>${formatTrackingValue(item.mean_boundary_distance_mm, 2)} mm</strong></div>`,
        `<div class="research-metric-row"><span>平均位移</span><strong>${formatTrackingValue(item.mean_flow_px, 2)} px</strong></div>`,
        '</div>',
        trackingSvg(tracking?.pairs, regionKey),
        '</article>'
      ].join('');
    }).filter(Boolean).join('');

    panel.innerHTML = [
      '<div class="research-panel-head"><strong>2D 应变与追踪验证</strong><span>相位曲线 / 光流验证</span></div>',
      `<div class="inline-actions wrap"><button type="button" class="ghost-button" data-cvi-run-tracking="1" ${running ? 'disabled' : ''}>${running ? '计算中...' : '运行追踪验证'}</button></div>`,
      error ? `<div class="status">${error}</div>` : '',
      strainCards ? `<div class="research-summary">${strainCards}${strainQualityCards}</div>` : '',
      strain ? strainChart(strain) : '',
      tracking ? `<div class="research-summary"><div class="research-summary-card"><span>人工相邻相位对</span><strong>${formatTrackingValue(tracking.pair_count, 0)}</strong></div><div class="research-summary-card"><span>候选对</span><strong>${formatTrackingValue(tracking.candidate_pair_count, 0)}</strong></div></div>` : '',
      regionCards
        ? `<div class="research-grid">${regionCards}</div>`
        : `<div class="empty-state">${tracking ? '当前没有可比较的相邻人工帧；仅有不相邻的 ED/ES 时结果应为 0。' : '追踪验证只比较相邻且标记为手工/手工修正的 phase，不会把传播帧当作真值。'}</div>`
    ].join('');
    panel.querySelector('[data-cvi-run-tracking="1"]')?.addEventListener('click', () => {
      void runTrackingPreview(Number(series.id));
    });
  };

  const ensureResearchPanelInteractions = () => {
    const cards = Array.from(document.querySelectorAll('[data-cvi-research-card="1"]'));
    if (!cards.length) {
      return;
    }

    if (activeResearchFocus.key) {
      const hasActiveCard = cards.some((card) => {
        return parseResearchCardData(card)?.key === activeResearchFocus.key;
      });
      if (!hasActiveCard) {
        clearResearchFocus();
      }
    }

    cards.forEach((card) => {
      if (!(card instanceof HTMLElement)) return;
      if (card.dataset.cviResearchBound !== '1') {
        card.dataset.cviResearchBound = '1';
        card.tabIndex = 0;
        card.addEventListener('click', () => focusResearchCard(card));
        card.addEventListener('keydown', (event) => {
          if (event.key !== 'Enter' && event.key !== ' ') return;
          event.preventDefault();
          focusResearchCard(card);
        });
      }
      if (!card.title) {
        card.title = '点击后高亮对应 Slice / Phase，并跳转到来源图像。';
      }
    });

    applyResearchFocusVisuals();
  };

  const handleArrowNavigation = (event) => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    if (isTypingTarget(event.target)) return;
    if (shouldHideProtocolPhaseControls()) return;

    const sliceInput = getNavigatorInput('Slice');
    const phaseInput = getNavigatorInput('Phase');
    if (!sliceInput && !phaseInput) return;

    let handled = false;
    if (event.key === 'ArrowLeft') handled = stepNavigatorInput(phaseInput, -1);
    if (event.key === 'ArrowRight') handled = stepNavigatorInput(phaseInput, 1);
    if (event.key === 'ArrowUp') handled = stepNavigatorInput(sliceInput, -1);
    if (event.key === 'ArrowDown') handled = stepNavigatorInput(sliceInput, 1);

    if (handled) {
      event.preventDefault();
      event.stopPropagation();
    }
  };

  const apply = () => {
    safeEnsureProtocolPhaseControlsVisibility();
    try {
      hideSeriesOverviewToolbar();
      ensureOverviewSeriesRoleControls();
    } catch {}
    inspectorTabKey = readInspectorTab();
    setRootVars();
    ensureWorkspaceHandles();
    ensureViewerHandles();
    ensureReferenceStacks();
    ensure4chRoleWarning();
    fitViewerStages();
    removeViewerProtocolEntry();
    syncContourToolControls();
    renameContourTargetSection();
    ensureExcludeRegionControls();
    ensureExcludePointToolGuard();
    ensureAutoFitButton();
    ensureLaxSeriesSelector();
    ensure4chZoomButton();
    ensure4chRuler();
    ensureContourContextTools();
    syncContourHandleHitTargets();
    ensureDrawContourStaysOpen();
    ensureDrawContourPreview();
    ensureTrackingValidationPanel();
    ensureLeftAtrialFunctionPanel();
    ensureFatThresholdPanel();
    ensureLgeThresholdPanelPlacement();
    ensureResearchPanelInteractions();
    ensureAnnotationOverlay();
    ensureMatrixSourceBadges();
    ensureMatrixSourceLegend();
    ensureMatrixCornerLayout();
    rollbackInspectorTabbedLayout();
    ensureInspectorSafeTabs();
    ensureWorkstationVersionBadge();
    safeEnsureProtocolPhaseControlsVisibility();
    ensureAutosaveFlushHooks();
    autoDetectEdEs();
  };

  let applyScheduled = false;
  let observer = null;
  const scheduleApply = () => {
    if (applyScheduled) return;
    applyScheduled = true;
    window.requestAnimationFrame(() => {
      applyScheduled = false;
      if (observer) observer.disconnect();
      try {
        apply();
      } finally {
        if (observer && document.body) {
          observer.observe(document.body, { childList: true, subtree: true });
        }
      }
    });
  };

  observer = new MutationObserver(scheduleApply);
  observer.observe(document.body, { childList: true, subtree: true });
  document.addEventListener('pointerdown', (event) => {
    if (activeContourMenu?.menu && event.target instanceof Element && activeContourMenu.menu.contains(event.target)) return;
    closeContourMenu();
  }, true);
  document.addEventListener('pointerdown', handleRulerPointerDown, true);
  document.addEventListener('pointermove', handleRulerPointerMove, true);
  document.addEventListener('pointerup', handleRulerPointerUp, true);
  document.addEventListener('pointercancel', handleRulerPointerUp, true);
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeContourMenu();
      if (rulerState.active && rulerState.start) {
        clearRuler();
      } else if (rulerState.active) {
        setRulerActive(false);
      }
    }
  }, true);
  window.addEventListener('resize', closeContourMenu);
  window.addEventListener('scroll', closeContourMenu, true);
  window.addEventListener('keydown', handleArrowNavigation, true);
  window.addEventListener('cvi:contours-updated', () => {
    safeEnsureProtocolPhaseControlsVisibility();
    if (fatThresholdState.enabled && isFunctionProtocolActive()) {
      queueFatThresholdPreview();
    }
    if (isLgeProtocolActive()) {
      queueLgeThresholdPreview();
    }
    scheduleApply();
  });
  window.addEventListener('cvi:measurements-updated', (event) => {
    if (event?.detail?.module === 'function' && isFunctionProtocolActive()) {
      fatThresholdState.status = '本序列指标已重算';
    }
    if (event?.detail?.module === 'lge' && isLgeProtocolActive()) {
      queueLgeThresholdPreview();
    }
    scheduleApply();
  });
  window.addEventListener('cvi:series-cache-updated', scheduleApply);
  window.addEventListener('load', () => {
    safeEnsureProtocolPhaseControlsVisibility();
    scheduleApply();
  });
  window.addEventListener('resize', () => {
    safeEnsureProtocolPhaseControlsVisibility();
    scheduleApply();
  });
  document.addEventListener('click', () => {
    window.setTimeout(safeEnsureProtocolPhaseControlsVisibility, 0);
  }, true);
  document.addEventListener('keyup', () => {
    window.setTimeout(safeEnsureProtocolPhaseControlsVisibility, 0);
  }, true);
  document.addEventListener('wheel', () => {
    if (rulerState.active) window.setTimeout(scheduleApply, 50);
  }, true);
  window.setInterval(safeEnsureProtocolPhaseControlsVisibility, 400);
  window.setInterval(() => {
    try {
      hideSeriesOverviewToolbar();
      ensureOverviewSeriesRoleControls();
      ensureWorkstationVersionBadge();
    } catch {}
  }, 400);
  scheduleApply();
})();
