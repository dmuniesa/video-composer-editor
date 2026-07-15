import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, media, fmtTime } from '../lib/api'
import { useProjectEvents } from '../lib/sse'
import type { FaceInfo, Person } from '../lib/types'
import InfoTip from '../components/InfoTip'

/** Open the clip at the face's exact moment, in a new tab so the People page
 *  stays where it is. */
const openFaceVideo = (pid: string, f: FaceInfo) =>
  window.open(`/p/${pid}/review?video=${f.video_id}&t=${f.t.toFixed(2)}`, '_blank')

function PersonCard({
  pid,
  person,
  others,
  onToast,
  onView,
}: {
  pid: string
  person: Person
  others: Person[]
  onToast: (msg: string) => void
  onView: (face: FaceInfo) => void
}) {
  const [name, setName] = useState(person.name)
  const [open, setOpen] = useState(false)
  const [faces, setFaces] = useState<FaceInfo[] | null>(null)

  useEffect(() => setName(person.name), [person.name])
  useEffect(() => {
    if (open) api.personFaces(pid, person.id).then(setFaces).catch((e) => onToast(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, person.face_count, person.cover_face_id])

  const commitName = () => {
    const next = name.trim()
    if (next === person.name) return
    const clash = others.find((p) => p.name && p.name.toLowerCase() === next.toLowerCase())
    api
      .updatePerson(pid, person.id, { name: next })
      .then(() => {
        if (clash) onToast(`Merged into "${clash.name}" — same name, same person.`)
      })
      .catch((e) => {
        onToast(e.message)
        setName(person.name)
      })
  }

  const label = (p: Person) => p.name || `Unnamed #${p.id}`

  return (
    <div className={`person-card ${person.name ? '' : 'unnamed'} ${person.hidden ? 'hidden-person' : ''}`}>
      <div className="person-head">
        {person.cover_face_id != null ? (
          <img className="person-cover" src={media.face(pid, person.cover_face_id)} alt="" />
        ) : (
          <div className="person-cover placeholder">?</div>
        )}
        <div className="person-info">
          <input
            className="person-name"
            placeholder="Name this person…"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={commitName}
            onKeyDown={(e) => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
              if (e.key === 'Escape') setName(person.name)
            }}
          />
          <div className="person-meta">
            <span
              className="person-meta-faces"
              title={open ? 'Hide the face grid' : 'Show the face grid'}
              onClick={() => setOpen(!open)}
            >
              {person.face_count} face{person.face_count === 1 ? '' : 's'}
            </span>{' '}
            · {person.videos.length} video{person.videos.length === 1 ? '' : 's'}
          </div>
          <div className="person-videos">
            {person.videos.slice(0, 4).map((v) => (
              <Link key={v.id} to={`/p/${pid}/review?video=${v.id}`} className="tag" title={v.filename}>
                {v.filename}
              </Link>
            ))}
            {person.videos.length > 4 && <span className="tag">+{person.videos.length - 4}</span>}
          </div>
        </div>
        <div className="person-actions">
          <button className="small" onClick={() => setOpen(!open)}>
            {open ? 'Hide faces' : 'Faces'}
          </button>
          {(!person.name || person.hidden) && (
            <button
              className="small"
              title={
                person.hidden
                  ? 'Show this person in the list again'
                  : "Not interested in this person — hide them from the list. Their faces are kept and new detections still match them silently."
              }
              onClick={() =>
                api.updatePerson(pid, person.id, { hidden: !person.hidden }).catch((e) => onToast(e.message))
              }
            >
              {person.hidden ? 'Unhide' : 'Hide'}
            </button>
          )}
          {others.length > 0 && (
            <select
              className="small"
              value=""
              title="Move all of this person's faces into another person"
              onChange={(e) => {
                const into = Number(e.target.value)
                if (!into) return
                const target = others.find((p) => p.id === into)
                if (confirm(`Merge "${label(person)}" into "${target ? label(target) : into}"?`))
                  api.mergePerson(pid, person.id, into).catch((err) => onToast(err.message))
                e.target.value = ''
              }}
            >
              <option value="">Merge into…</option>
              {others.map((p) => (
                <option key={p.id} value={p.id}>{label(p)}</option>
              ))}
            </select>
          )}
          <button
            className="small danger"
            title="Dissolve this person; its faces become unassigned (a re-cluster may group them again)"
            onClick={() => {
              if (confirm(`Dissolve "${label(person)}"? The detected faces are kept but lose the assignment.`))
                api.deletePerson(pid, person.id).catch((e) => onToast(e.message))
            }}
          >
            ✕
          </button>
        </div>
      </div>
      {open && (
        <div className="face-grid">
          {(faces ?? []).map((f) => (
            <div
              key={f.id}
              className={`face-tile ${f.id === person.cover_face_id ? 'cover' : ''}`}
              title={`${f.filename} · ${fmtTime(f.t)} · score ${f.det_score.toFixed(2)}${f.similarity != null ? ` · sim ${f.similarity.toFixed(2)}` : ''}\nClick to view it large`}
            >
              <img src={media.face(pid, f.id)} alt="" loading="lazy" onClick={() => onView(f)} />
              <div className="face-actions">
                <button
                  title="Open the video at this exact moment (new tab)"
                  onClick={() => openFaceVideo(pid, f)}
                >
                  👁
                </button>
                <button
                  title="Use this face as the person's cover"
                  onClick={() =>
                    api.updatePerson(pid, person.id, { cover_face_id: f.id }).catch((e) => onToast(e.message))
                  }
                >
                  📌
                </button>
                <button
                  title="Not this person — detach the face"
                  onClick={() => api.updateFace(pid, f.id, { person_id: null }).catch((e) => onToast(e.message))}
                >
                  ↷
                </button>
                <button
                  title="Not a person / false positive — ignore this face"
                  onClick={() => api.updateFace(pid, f.id, { ignored: true }).catch((e) => onToast(e.message))}
                >
                  🚫
                </button>
              </div>
            </div>
          ))}
          {faces != null && faces.length === 0 && <span className="hint">no faces</span>}
        </div>
      )}
    </div>
  )
}

/** Lightbox: the full sampled frame with the face's bbox highlighted. */
function FaceViewer({ pid, face, onClose }: { pid: string; face: FaceInfo; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="detail-overlay" onClick={onClose}>
      <div className="face-viewer" onClick={(e) => e.stopPropagation()}>
        <div className="face-frame-wrap">
          <img src={media.faceFrame(pid, face.id)} alt="" />
          <div
            className="face-bbox"
            style={{
              left: `${face.x * 100}%`,
              top: `${face.y * 100}%`,
              width: `${face.w * 100}%`,
              height: `${face.h * 100}%`,
            }}
          />
        </div>
        <div className="face-viewer-bar">
          <span className="hint">
            {face.filename} · {fmtTime(face.t)} · score {face.det_score.toFixed(2)}
            {face.similarity != null && <> · sim {face.similarity.toFixed(2)}</>}
          </span>
          <span className="spacer" />
          <button className="primary small" onClick={() => openFaceVideo(pid, face)}>
            ▶ Open in video
          </button>
          <button className="small" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  )
}

export default function PeoplePage({ pid }: { pid: string }) {
  const [available, setAvailable] = useState(true)
  const [reason, setReason] = useState<string | null>(null)
  const [persons, setPersons] = useState<Person[]>([])
  const [loaded, setLoaded] = useState(false)
  const [detecting, setDetecting] = useState(false)
  const [viewFace, setViewFace] = useState<FaceInfo | null>(null)
  const [toast, setToast] = useState('')

  const refresh = useCallback(() => {
    api
      .people(pid)
      .then((r) => {
        setAvailable(r.available)
        setReason(r.reason)
        setPersons(r.persons)
        setLoaded(true)
      })
      .catch((e) => setToast(e.message))
  }, [pid])
  useEffect(refresh, [refresh])
  useProjectEvents(pid, (e) => {
    if (e.event === 'people') refresh()
    if (e.event === 'job') {
      const job = e.data as { kind?: string; status?: string }
      if (job.kind === 'faces' && (job.status === 'done' || job.status === 'error')) setDetecting(false)
    }
  })

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(''), 4000)
    return () => clearTimeout(t)
  }, [toast])

  const detect = (force = false) => {
    setDetecting(true)
    api
      .detectFaces(pid, undefined, force)
      .then(({ queued }) => {
        setToast(
          queued > 0
            ? `Detecting people in ${queued} clip${queued === 1 ? '' : 's'}… (the first run downloads the face model)`
            : 'Nothing to do — every ready clip is already processed. Use force to redo.',
        )
        if (queued === 0) setDetecting(false)
      })
      .catch((e) => {
        setToast(e.message)
        setDetecting(false)
      })
  }

  const [showHidden, setShowHidden] = useState(false)
  const visible = persons.filter((p) => !p.hidden)
  const named = visible.filter((p) => p.name)
  const unnamed = visible.filter((p) => !p.name)
  const hidden = persons.filter((p) => p.hidden)

  return (
    <div className="people-page">
      <div className="filter-bar">
        <span>
          {named.length} named · {unnamed.length} unnamed
        </span>
        <button className="primary small" disabled={!available || detecting} onClick={() => detect(false)}>
          🔍 Detect people
        </button>
        <button
          className="small"
          disabled={!available || detecting}
          title="Re-detect every clip from scratch (keeps named people, re-matches their faces)"
          onClick={() => {
            if (confirm('Re-run detection on ALL clips? Named people are kept; their faces are re-matched.')) detect(true)
          }}
        >
          Re-detect all
        </button>
        <button
          className="small"
          disabled={!available}
          title="Dissolve unnamed groups and re-group the unassigned faces. Named people are never touched."
          onClick={() => api.reclusterPeople(pid).catch((e) => setToast(e.message))}
        >
          ♻ Re-cluster
        </button>
        <InfoTip>
          <b>People</b>
          <ul>
            <li><b>Detect people</b> samples frames from each clip and finds faces (runs locally, no cloud).</li>
            <li>Similar faces are grouped automatically. <b>Type a name</b> on a group to identify that person.</li>
            <li>Typing a name that <b>already exists merges</b> the two groups — quickest way to fix a split person.</li>
            <li><b>Hide</b> an unnamed group you're not interested in (strangers in the background): it leaves the list, but its faces are kept so new detections keep matching it instead of creating new groups.</li>
            <li>Named people are matched automatically in newly detected clips — and every confirmed face makes future matches easier.</li>
            <li>Open <b>Faces</b>: click a face to view it large, 👁 opens the video at that exact moment (new tab), 📌 makes it the cover, ↷ detaches it, 🚫 ignores a false positive.</li>
            <li>Named people appear as chips on the Review page — filter with <b>@name</b>.</li>
          </ul>
        </InfoTip>
      </div>

      {!available && (
        <div className="empty-note">
          <p>People detection is not installed.</p>
          <p className="hint">{reason}</p>
        </div>
      )}

      {available && loaded && persons.length === 0 && (
        <div className="empty-note">
          No people detected yet. Scan and extract your clips on Setup, then press <b>Detect people</b>.
        </div>
      )}

      {named.length > 0 && (
        <>
          <h3 className="people-section">People</h3>
          {named.map((p) => (
            <PersonCard key={p.id} pid={pid} person={p} others={persons.filter((o) => o.id !== p.id)} onToast={setToast} onView={setViewFace} />
          ))}
        </>
      )}

      {unnamed.length > 0 && (
        <>
          <h3 className="people-section">Unnamed — give them a name</h3>
          {unnamed.map((p) => (
            <PersonCard key={p.id} pid={pid} person={p} others={persons.filter((o) => o.id !== p.id)} onToast={setToast} onView={setViewFace} />
          ))}
        </>
      )}

      {hidden.length > 0 && (
        <>
          <h3 className="people-section people-hidden-toggle" onClick={() => setShowHidden(!showHidden)}>
            {showHidden ? '▾' : '▸'} Hidden ({hidden.length}) — people you're not interested in
          </h3>
          {showHidden &&
            hidden.map((p) => (
              <PersonCard key={p.id} pid={pid} person={p} others={persons.filter((o) => o.id !== p.id)} onToast={setToast} onView={setViewFace} />
            ))}
        </>
      )}

      {viewFace && <FaceViewer pid={pid} face={viewFace} onClose={() => setViewFace(null)} />}
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
