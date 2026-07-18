/** Tiny inline SVG icon set (16px, stroke = currentColor) used by the montage toolbar. */

const base = {
  width: 15,
  height: 15,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.9,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
}

export const IcUndo = () => (
  <svg {...base}>
    <path d="M9 14 4 9l5-5" />
    <path d="M4 9h10a6 6 0 0 1 0 12h-3" />
  </svg>
)

export const IcRedo = () => (
  <svg {...base}>
    <path d="m15 14 5-5-5-5" />
    <path d="M20 9H10a6 6 0 0 0 0 12h3" />
  </svg>
)

export const IcZoomIn = () => (
  <svg {...base}>
    <circle cx="11" cy="11" r="7" />
    <path d="m21 21-4.3-4.3M8 11h6M11 8v6" />
  </svg>
)

export const IcZoomOut = () => (
  <svg {...base}>
    <circle cx="11" cy="11" r="7" />
    <path d="m21 21-4.3-4.3M8 11h6" />
  </svg>
)

export const IcMagnet = () => (
  <svg {...base}>
    <path d="M6 3v8a6 6 0 0 0 12 0V3" />
    <path d="M6 3h4v5H6zM14 3h4v5h-4z" fill="currentColor" stroke="none" />
  </svg>
)

export const IcTrackPlus = () => (
  <svg {...base}>
    <rect x="3" y="14" width="18" height="5" rx="1" />
    <rect x="3" y="5" width="10" height="5" rx="1" />
    <path d="M19 4v6M16 7h6" />
  </svg>
)

export const IcTrackMinus = () => (
  <svg {...base}>
    <rect x="3" y="14" width="18" height="5" rx="1" />
    <rect x="3" y="5" width="10" height="5" rx="1" />
    <path d="M16 7h6" />
  </svg>
)

export const IcGear = () => (
  <svg {...base}>
    <circle cx="12" cy="12" r="3.2" />
    <path d="M12 2.8v3M12 18.2v3M2.8 12h3M18.2 12h3M5.5 5.5l2.1 2.1M16.4 16.4l2.1 2.1M18.5 5.5l-2.1 2.1M7.6 16.4l-2.1 2.1" />
  </svg>
)

export const IcSkipBack = () => (
  <svg {...base}>
    <path d="M19 20 9 12l10-8z" fill="currentColor" stroke="none" />
    <path d="M5 5v14" />
  </svg>
)

export const IcPlay = () => (
  <svg {...base}>
    <path d="M7 4.5 19 12 7 19.5z" fill="currentColor" stroke="none" />
  </svg>
)

export const IcPause = () => (
  <svg {...base}>
    <rect x="6" y="4.5" width="4" height="15" rx="1" fill="currentColor" stroke="none" />
    <rect x="14" y="4.5" width="4" height="15" rx="1" fill="currentColor" stroke="none" />
  </svg>
)

export const IcMonitor = () => (
  <svg {...base}>
    <rect x="3" y="4" width="18" height="12" rx="2" />
    <path d="M8 20h8M12 16v4" />
  </svg>
)

export const IcDownload = () => (
  <svg {...base}>
    <path d="M12 3v11M7.5 9.5 12 14l4.5-4.5" />
    <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
  </svg>
)

export const IcChevronDown = () => (
  <svg {...base} width={11} height={11}>
    <path d="m6 9 6 6 6-6" />
  </svg>
)

export const IcRefresh = () => (
  <svg {...base}>
    <path d="M21 12a9 9 0 1 1-2.6-6.4" />
    <path d="M21 3v6h-6" />
  </svg>
)

export const IcSparkles = () => (
  <svg {...base}>
    <path d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6z" fill="currentColor" stroke="none" />
    <path d="M18.5 14.5l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7z" fill="currentColor" stroke="none" />
  </svg>
)

export const IcTrash = () => (
  <svg {...base}>
    <path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M10 11v6M14 11v6" />
  </svg>
)

export const IcMic = () => (
  <svg {...base}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
  </svg>
)

export const IcFilter = () => (
  <svg {...base}>
    <path d="M3 5h18l-7 8v6l-4-2v-4z" />
  </svg>
)

export const IcUsers = () => (
  <svg {...base}>
    <circle cx="9" cy="8" r="3.2" />
    <path d="M3.5 19a5.5 5.5 0 0 1 11 0M16 5.2a3.2 3.2 0 0 1 0 6M17 19a5.5 5.5 0 0 0-3-4.9" />
  </svg>
)

export const IcShuffle = () => (
  <svg {...base}>
    <path d="M3 7h3.5l8 10H21M3 17h3.5l2.4-3M14 7l2.6-3M18 4h3v3M18 20h3v-3" />
  </svg>
)

export const IcVolumeOn = () => (
  <svg {...base}>
    <path d="M4 9v6h4l5 4V5L8 9H4z" fill="currentColor" stroke="none" />
    <path d="M16 8.5a4.5 4.5 0 0 1 0 7M18.5 6a8 8 0 0 1 0 12" />
  </svg>
)

export const IcVolumeOff = () => (
  <svg {...base}>
    <path d="M4 9v6h4l5 4V5L8 9H4z" fill="currentColor" stroke="none" />
    <path d="m16 9.5 4.5 5M20.5 9.5 16 14.5" />
  </svg>
)

export const IcLevels = () => (
  <svg {...base}>
    <path d="M5 21v-6M5 10V3M12 21v-9M12 7V3M19 21v-4M19 12V3" />
    <path d="M3 8h4M10 14h4M17 16h4" />
  </svg>
)

export const IcNormalize = () => (
  <svg {...base}>
    <path d="M4 21V11M8 21V5M12 21V8M16 21V13" />
    <path d="M20 7v10M20 7l-2.2 2.2M20 7l2.2 2.2M20 17l-2.2-2.2M20 17l2.2-2.2" />
  </svg>
)

// ---- context-menu icons (same 15px language as the toolbar) ----

export const IcPlus = () => (
  <svg {...base}>
    <path d="M12 5v14M5 12h14" />
  </svg>
)

/** crop/selection brackets — placing a sub-range of a clip */
export const IcRange = () => (
  <svg {...base}>
    <path d="M6 9V6h3M18 9V6h-3M6 15v3h3M18 15v3h-3" />
  </svg>
)

/** film strip — details / player / ranges & tags */
export const IcFilm = () => (
  <svg {...base}>
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <path d="M7 3v18M17 3v18M3 7.5h4M3 12h18M17 7.5h4M3 16.5h4M17 16.5h4" />
  </svg>
)

export const IcStar = () => (
  <svg {...base}>
    <path d="M12 17.8l-6.2 3.2 1.2-6.9-5-4.9 6.9-1L12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.9z" />
  </svg>
)

export const IcScissors = () => (
  <svg {...base}>
    <circle cx="6" cy="6" r="2.6" />
    <circle cx="6" cy="18" r="2.6" />
    <path d="M20 4 8.5 15.5M14.5 14.5 20 20M8.5 8.5 12 12" />
  </svg>
)

/** a clip block being shifted left — ripple delete / close gap */
export const IcRipple = () => (
  <svg {...base}>
    <rect x="13" y="7" width="7" height="10" rx="1" />
    <path d="M11 12H3.5M7 8 3.5 12 7 16" />
  </svg>
)

