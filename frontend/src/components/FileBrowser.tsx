import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { FsListing } from '../lib/types'

interface Props {
  /** 'dir' picks directories, 'audio' picks audio files */
  mode: 'dir' | 'audio'
  onPick: (path: string) => void
  initialPath?: string
}

export default function FileBrowser({ mode, onPick, initialPath }: Props) {
  const [listing, setListing] = useState<FsListing | null>(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState('')

  const load = (path: string) =>
    api
      .fsList(path)
      .then((l) => {
        setListing(l)
        setError('')
      })
      .catch((e) => setError(String(e.message ?? e)))

  useEffect(() => {
    load(initialPath ?? '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (error) return <div className="error-text">{error}</div>
  if (!listing) return <div className="hint">loading…</div>

  const join = (name: string) =>
    listing.path.endsWith('/') ? listing.path + name : `${listing.path}/${name}`

  return (
    <div>
      <div className="crumb">{listing.path}</div>
      <div className="file-browser">
        {listing.parent && (
          <div className="row" onDoubleClick={() => load(listing.parent!)} onClick={() => load(listing.parent!)}>
            📁 ..
          </div>
        )}
        {listing.dirs.map((d) => (
          <div key={d} className="row" onClick={() => load(join(d))}>
            📁 {d}
          </div>
        ))}
        {mode === 'audio' &&
          listing.audios.map((f) => (
            <div
              key={f}
              className={`row file ${selected === join(f) ? 'selected' : ''}`}
              onClick={() => setSelected(join(f))}
              onDoubleClick={() => onPick(join(f))}
            >
              🎵 {f}
            </div>
          ))}
        {listing.videos.map((f) => (
          <div key={f} className="row file">
            🎞️ {f}
          </div>
        ))}
      </div>
      <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
        {mode === 'dir' ? (
          <button className="primary" onClick={() => onPick(listing.path)}>
            Use this folder ({listing.videos.length} videos here)
          </button>
        ) : (
          <button className="primary" disabled={!selected} onClick={() => selected && onPick(selected)}>
            Use selected song
          </button>
        )}
      </div>
    </div>
  )
}
