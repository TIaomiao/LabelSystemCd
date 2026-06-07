# Performance Optimization Report

## Overview
This document outlines the performance optimization strategies implemented in the CMR Label System.

## Strategies

### 1. Backend Data Handling
- **Lazy Metadata Extraction**: Uses `pydicom.dcmread(..., stop_before_pixels=True)` to extract `SliceLocation` and `TemporalPosition` without loading the heavy pixel data. This ensures fast response times for file listings.
- **Efficient File Scanning**: Scans directories only when requested.
- **Streaming**: DICOM files are served individually, allowing the browser to parallelize downloads.

### 2. Frontend Rendering (Cornerstone.js)
- **On-Demand Loading**: Images are loaded into memory only when required for display or pre-fetching.
- **Web Workers**: `cornerstone-wado-image-loader` uses Web Workers for DICOM decoding, preventing UI main thread blocking during heavy decoding tasks.
- **Canvas Rendering**: Uses HTML5 Canvas for high-performance 60fps rendering of medical images.

### 3. Network
- **Minimal API Payload**: File lists return only necessary metadata (filename, slice info) to minimize JSON size.
- **HTTP/2 Ready**: The architecture supports HTTP/2 (if served via Nginx/Apache) for multiplexed downloads.

## Future Improvements
- **Server-Side Rendering (SSR) for Thumbnails**: Generate JPEG thumbnails on backend to speed up gallery views (partially implemented).
- **Metadata Caching**: Cache the parsed DICOM metadata in a local SQLite DB or JSON file to avoid re-parsing on every request.
- **Compression**: Enable GZIP/Brotli on the web server level.
