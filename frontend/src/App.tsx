import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { api } from './lib/api'
import { useProjectEvents } from './lib/sse'
import type { JobInfo, ProjectInfo } from './lib/types'
import SetupPage from './pages/SetupPage'
import ReviewPage from './pages/ReviewPage'
import MusicPage from './pages/MusicPage'
import MontagePage from './pages/MontagePage'

function ProjectShell() {
  const { pid = '' } = useParams()
  const [project, setProject] = useState<ProjectInfo | null>(null)
  const [jobs, setJobs] = useState<JobInfo[]>([])

  const refreshProject = () => api.getProject(pid).then(setProject).catch(() => setProject(null))
  useEffect(() => {
    refreshProject()
    api.jobs(pid).then(setJobs).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid])

  useProjectEvents(pid, (e) => {
    if (e.event === 'job') {
      const job = e.data as unknown as JobInfo
      setJobs((prev) => {
        const next = prev.filter((j) => j.id !== job.id)
        if (job.status === 'queued' || job.status === 'running') next.push(job)
        return next.sort((a, b) => a.id - b.id)
      })
      if (job.status === 'done' || job.status === 'error') refreshProject()
    }
  })

  const active = jobs.filter((j) => j.status === 'queued' || j.status === 'running')

  return (
    <div className="app-shell">
      <nav className="app-nav">
        <span className="brand">🎬 Montage</span>
        <NavLink to={`/p/${pid}/setup`}>Setup</NavLink>
        <NavLink to={`/p/${pid}/review`}>Review</NavLink>
        <NavLink to={`/p/${pid}/music`}>Music</NavLink>
        <NavLink to={`/p/${pid}/montage`}>Montage</NavLink>
        <span className="spacer" />
        <span className="hint">{project?.name ?? ''}</span>
      </nav>
      <main className="app-main">
        <Routes>
          <Route path="setup" element={<SetupPage project={project} onChanged={refreshProject} />} />
          <Route path="review" element={<ReviewPage pid={pid} />} />
          <Route path="music" element={<MusicPage pid={pid} />} />
          <Route path="montage" element={<MontagePage pid={pid} />} />
          <Route path="*" element={<Navigate to="setup" replace />} />
        </Routes>
      </main>
      <footer className="jobs-bar">
        {active.length === 0 ? (
          <span>idle</span>
        ) : (
          active.slice(0, 3).map((j) => (
            <span key={j.id} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              {j.label} {j.message && `· ${j.message}`}
              <span className="bar">
                <div style={{ width: `${Math.round(j.progress * 100)}%` }} />
              </span>
            </span>
          ))
        )}
        {active.length > 3 && <span>+{active.length - 3} more</span>}
      </footer>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<SetupPage project={null} onChanged={() => {}} standalone />} />
      <Route path="/p/:pid/*" element={<ProjectShell />} />
    </Routes>
  )
}
