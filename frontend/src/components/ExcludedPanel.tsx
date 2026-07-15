import type { ExcludedFile } from '../lib/types'

/** Lists files the user deleted in Review (tombstones that a rescan keeps
 * skipping) and lets them be restored one by one or all at once. Restoring is
 * handled by the parent, which drops the tombstone and rescans to re-add the
 * clip. */
export default function ExcludedPanel({
  excluded,
  onRestore,
  onClose,
}: {
  excluded: ExcludedFile[]
  onRestore: (eid: number) => void
  onClose: () => void
}) {
  return (
    <div className="detail-overlay" onClick={onClose}>
      <div className="excluded-modal" onClick={(e) => e.stopPropagation()}>
        <div className="detail-header">
          <h3>Deleted clips ({excluded.length})</h3>
          {excluded.length > 0 && (
            <button className="small" onClick={() => excluded.forEach((e) => onRestore(e.id))}>
              Restore all
            </button>
          )}
          <button className="small" onClick={onClose}>
            Close
          </button>
        </div>
        <p className="hint">
          These files were removed from the project but kept on disk. A rescan skips them so they don't
          come back. Restore one to add it back and re-scan its folder.
        </p>
        {excluded.length === 0 ? (
          <div className="empty-note">Nothing deleted — this list is empty.</div>
        ) : (
          <ul className="excluded-list">
            {excluded.map((e) => (
              <li key={e.id}>
                <div className="excluded-info">
                  <span className="excluded-name">{e.filename || e.rel_path}</span>
                  <span className="excluded-path">{e.rel_path}</span>
                </div>
                <button className="small" onClick={() => onRestore(e.id)}>
                  Restore
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
