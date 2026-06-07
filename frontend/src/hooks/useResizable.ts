import { useState, useCallback, useEffect, useRef } from 'react';

interface UseResizableProps {
  initialWidth: number;
  minWidth?: number;
  maxWidth?: number;
  direction?: 'right' | 'left'; // 'right' means handle is on the right (for left sidebar), 'left' means handle is on the left (for right sidebar)
  storageKey?: string; // Optional key for persistence
}

export function useResizable({
  initialWidth,
  minWidth = 200,
  maxWidth = 800,
  direction = 'right',
  storageKey
}: UseResizableProps) {
  const [width, setWidth] = useState(() => {
    if (storageKey) {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        const parsed = parseFloat(saved);
        if (!isNaN(parsed)) return parsed;
      }
    }
    return initialWidth;
  });
  
  const [isResizing, setIsResizing] = useState(false);
  const startX = useRef<number>(0);
  const startWidth = useRef<number>(0);

  // Persist width changes
  useEffect(() => {
    if (storageKey) {
      localStorage.setItem(storageKey, width.toString());
    }
  }, [width, storageKey]);

  const startResizing = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
    startX.current = e.clientX;
    startWidth.current = width;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [width]);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing) return;

      const delta = e.clientX - startX.current;
      const newWidth = startWidth.current + (direction === 'right' ? delta : -delta);

      if (newWidth >= minWidth && newWidth <= maxWidth) {
        setWidth(newWidth);
      }
    };

    const handleMouseUp = () => {
      setIsResizing(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    if (isResizing) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
    }

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing, minWidth, maxWidth, direction]);

  return { width, startResizing, isResizing };
}
